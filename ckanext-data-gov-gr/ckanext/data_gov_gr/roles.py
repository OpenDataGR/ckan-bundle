"""
Επιπλέον ρόλοι μελών φορέα: «Κεντρικός Διαχειριστής» και «ΥΧΔ - DGO».

Οι ρόλοι αποθηκεύονται αυτούσιοι στο ``member.capacity`` (``central_admin`` /
``dgo``) και παίρνουν αντίγραφο των δικαιωμάτων του ``admin`` / ``member``.
Το CKAN δεν έχει plugin interface για νέους ρόλους, οπότε καταχωρίζονται στα
``ckan.authz.ROLE_PERMISSIONS`` και ``ckan.authz._trans_functions``.
"""
from __future__ import annotations

from typing import Optional

import ckan.plugins.toolkit as toolkit
from ckan import authz, model

CENTRAL_ADMIN = 'central_admin'
DGO = 'dgo'
NEW_ROLES = (CENTRAL_ADMIN, DGO)

# Ρόλοι με δικαιώματα διαχειριστή φορέα
ADMIN_CAPACITIES = ('admin', CENTRAL_ADMIN)

# Αντίστοιχος native ρόλος CKAN, για καταναλωτές που γνωρίζουν μόνο
# admin/editor/member
EFFECTIVE_ROLE = {
    CENTRAL_ADMIN: 'admin',
    DGO: 'member',
}

# Σειρά εμφάνισης στο dropdown ρόλων
ROLE_ORDER = (CENTRAL_ADMIN, 'admin', 'editor', 'member', DGO)

ROLE_LABELS_EL = {
    CENTRAL_ADMIN: 'Κεντρικός Διαχειριστής',
    'admin': 'Διαχειριστής',
    'editor': 'Συντάκτης',
    'member': 'Μέλος',
    DGO: 'Υπεύθυνος Χρήσης Δεδομένων (ΥΧΔ - DGO)',
}

ROLE_LABELS_EL_LOWER = {
    CENTRAL_ADMIN: 'κεντρικός διαχειριστής',
    'admin': 'διαχειριστής',
    'editor': 'συντάκτης',
    'member': 'μέλος',
    DGO: 'υπεύθυνος χρήσης δεδομένων (ΥΧΔ - DGO)',
}


def is_admin_capacity(capacity: Optional[str]) -> bool:
    return bool(capacity) and capacity.lower() in ADMIN_CAPACITIES


def effective_role(capacity: Optional[str]) -> Optional[str]:
    if not capacity:
        return capacity
    return EFFECTIVE_ROLE.get(capacity, capacity)


def register_org_roles() -> None:
    """Καταχωρίζει τους ρόλους στο CKAN. Ασφαλές να κληθεί πολλές φορές."""
    role_permissions = authz.ROLE_PERMISSIONS
    trans_functions = getattr(authz, '_trans_functions', None)

    if ('admin' not in role_permissions
            or 'member' not in role_permissions
            or not isinstance(trans_functions, dict)):
        raise RuntimeError(
            'data_gov_gr: μη υποστηριζόμενη δομή του ckan.authz, '
            'δεν μπορούν να καταχωριστούν οι ρόλοι central_admin/dgo'
        )

    roles = dict(role_permissions)
    roles[CENTRAL_ADMIN] = list(role_permissions['admin'])
    roles[DGO] = list(role_permissions['member'])

    ordered = [(role, roles.pop(role)) for role in ROLE_ORDER if role in roles]
    ordered.extend(roles.items())

    # In place, ώστε όσοι κρατούν reference στο dict να βλέπουν τις αλλαγές
    role_permissions.clear()
    role_permissions.update(ordered)

    trans_functions[CENTRAL_ADMIN] = lambda: toolkit._('Central Administrator')
    trans_functions[DGO] = lambda: toolkit._('Data Governance Officer (DGO)')

    authz.get_group_or_org_admin_ids = get_group_or_org_admin_ids


CASCADE_CONFIG = 'ckan.auth.roles_that_cascade_to_sub_groups'


def add_cascade_equivalents(config_) -> None:
    """Οι νέοι ρόλοι κληρονομούνται σε υπο-οργανισμούς όπως ο αντίστοιχος
    native ρόλος (π.χ. central_admin όπου κάνει cascade ο admin).

    Τα ``authz.has_user_permission_for_group_or_org`` και
    ``organization_list_for_user`` συγκρίνουν το capacity απευθείας με τη
    ρύθμιση, οπότε δεν αρκεί η αντιγραφή των δικαιωμάτων.
    """
    cascade = toolkit.aslist(config_.get(CASCADE_CONFIG))
    for role, native_role in EFFECTIVE_ROLE.items():
        if native_role in cascade and role not in cascade:
            cascade.append(role)
    config_[CASCADE_CONFIG] = cascade


def get_group_or_org_admin_ids(group_id: Optional[str]) -> list[str]:
    """Όπως το core ``authz.get_group_or_org_admin_ids`` αλλά περιλαμβάνει
    και τους Κεντρικούς Διαχειριστές."""
    if not group_id:
        return []
    group = model.Group.get(group_id)
    if not group:
        return []
    q = model.Session.query(model.Member.table_id) \
        .filter(model.Member.group_id == group.id) \
        .filter(model.Member.table_name == 'user') \
        .filter(model.Member.state == 'active') \
        .filter(model.Member.capacity.in_(ADMIN_CAPACITIES))

    return [a.table_id for a in q]
