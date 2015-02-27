"""
sentry.tasks.check_alerts
~~~~~~~~~~~~~~~~~~~~~~~~~

:copyright: (c) 2010-2014 by the Sentry Team, see AUTHORS for more details.
:license: BSD, see LICENSE for more details.
"""

from __future__ import absolute_import, division

import logging

from datetime import timedelta
from django.utils import timezone

from sentry.models import AuthIdentity, OrganizationMember
from sentry.tasks.base import instrumented_task


logger = logging.getLogger('auth')

AUTH_CHECK_INTERVAL = 3600


@instrumented_task(name='sentry.tasks.check_auth', queue='auth')
def check_auth(**kwargs):
    """
    Iterates over all accounts which have not been verified in the required
    interval and creates a new job to verify them.
    """
    # TODO(dcramer): we should remove identities if they've been inactivate
    # for a reasonable interval
    now = timezone.now()
    cutoff = now - timedelta(seconds=AUTH_CHECK_INTERVAL)
    identity_list = list(AuthIdentity.objects.filter(
        last_verified__lte=cutoff,
    ))
    AuthIdentity.objects.filter(
        id__in=[i.id for i in identity_list],
    ).update(last_verified=now)
    for identity in identity_list:
        check_auth_identity.apply_async(
            kwargs={'auth_identity_id': identity.id},
            expires=AUTH_CHECK_INTERVAL,
        )


@instrumented_task(name='sentry.tasks.check_auth_identity', queue='auth')
def check_auth_identity(auth_identity_id, **kwargs):
    try:
        auth_identity = AuthIdentity.objects.get(id=auth_identity_id)
    except AuthIdentity.DoesNotExist:
        logger.warning('AuthIdentity(id=%s) does not exist', auth_identity_id)
        return

    auth_provider = auth_identity.auth_provider
    provider = auth_provider.get_provider()
    try:
        is_valid = provider.identity_is_valid(auth_identity)
    except Exception:
        # to ensure security we count any kind of error as an invalidation
        # event
        logger.exception('AuthIdentity(id=%s) returned an error during validation', auth_identity_id)
        is_valid = False

    try:
        om = OrganizationMember.objects.get(
            user=auth_identity.user,
            organization=auth_provider.organization_id,
        )
    except OrganizationMember.DoesNotExist:
        logger.warning('Removing invalid AuthIdentity(id=%s) due to no organization access', auth_identity_id)
        auth_identity.delete()
        return

    if not is_valid:
        setattr(om.flags, 'sso:linked', False)
        setattr(om.flags, 'sso:invalid', True)
    else:
        setattr(om.flags, 'sso:linked', True)
        setattr(om.flags, 'sso:invalid', False)
    om.update(flags=om.flags)

    auth_identity.update(last_verified=timezone.now())
