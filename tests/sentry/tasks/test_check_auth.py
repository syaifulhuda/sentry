from __future__ import absolute_import, print_function

from datetime import timedelta
from django.utils import timezone
from mock import patch

from sentry.auth.providers.dummy import DummyProvider
from sentry.models import AuthIdentity, AuthProvider, OrganizationMember
from sentry.testutils import TestCase
from sentry.tasks.check_auth import (
    AUTH_CHECK_INTERVAL, check_auth, check_auth_identity
)


class CheckAuthTest(TestCase):
    @patch('sentry.tasks.check_auth.check_auth_identity')
    def test_simple(self, mock_check_auth_identity):
        organization = self.create_organization(name='Test')
        user = self.create_user(email='bar@example.com')
        auth_provider = AuthProvider.objects.create(
            organization=organization,
            provider='dummy',
        )
        om = OrganizationMember.objects.create(
            user=user,
            organization=organization,
            flags=getattr(OrganizationMember.flags, 'sso:linked'),
        )

        ai = AuthIdentity.objects.create(
            auth_provider=auth_provider,
            user=user,
            last_verified=timezone.now() - timedelta(days=1),
        )

        check_auth()

        updated_ai = AuthIdentity.objects.get(id=ai.id)
        assert updated_ai.last_verified != ai.last_verified

        mock_check_auth_identity.apply_async.assert_called_once_with(
            kwargs={'auth_identity_id': ai.id},
            expires=AUTH_CHECK_INTERVAL,
        )


class CheckAuthIdentityTest(TestCase):
    @patch('sentry.tasks.check_auth.check_auth_identity')
    def test_simple(self, mock_check_auth_identity):
        organization = self.create_organization(name='Test')
        user = self.create_user(email='bar@example.com')
        auth_provider = AuthProvider.objects.create(
            organization=organization,
            provider='dummy',
        )
        om = OrganizationMember.objects.create(
            user=user,
            organization=organization,
            flags=getattr(OrganizationMember.flags, 'sso:linked'),
        )

        ai = AuthIdentity.objects.create(
            auth_provider=auth_provider,
            user=user,
            last_verified=timezone.now() - timedelta(days=1),
        )

        with patch.object(DummyProvider, 'identity_is_valid') as mock_identity_is_valid:
            mock_identity_is_valid.return_value = False
            with self.auth_provider('dummy', DummyProvider):
                check_auth_identity(auth_identity_id=ai.id)
            mock_identity_is_valid.assert_called_once_with(ai)

        # because of an error, it should become inactive
        om = OrganizationMember.objects.get(id=om.id)
        assert not getattr(om.flags, 'sso:linked')
        assert getattr(om.flags, 'sso:invalid')

        updated_ai = AuthIdentity.objects.get(id=ai.id)
        assert updated_ai.last_verified != ai.last_verified
