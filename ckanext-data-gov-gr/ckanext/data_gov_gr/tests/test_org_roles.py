"""
Tests για τους ρόλους φορέα «Κεντρικός Διαχειριστής» (central_admin) και
«ΥΧΔ - DGO» (dgo).
"""
import pytest

import ckan.authz as authz
import ckan.model as model
import ckan.plugins.toolkit as toolkit
from ckan.lib.plugins import get_permission_labels
from ckan.tests import factories, helpers

from ckanext.data_gov_gr import commands, roles
from ckanext.data_gov_gr.logic import actions as dgg_actions
from ckanext.data_gov_gr.logic import auth


pytestmark = [
    # Το data_gov_gr κάνει chain auth functions του harvest
    pytest.mark.ckan_config("ckan.plugins", "activity harvest data_gov_gr"),
    pytest.mark.usefixtures("with_plugins", "clean_db", "no_search_index"),
]


@pytest.fixture
def clean_db(reset_db, migrate_db_for):
    # Όπως στα tests του ckanext-activity: το reset δεν εφαρμόζει τα
    # migrations των plugins
    reset_db()
    migrate_db_for("activity")
    migrate_db_for("harvest")


@pytest.fixture
def no_search_index(monkeypatch):
    # Τα tests δεν χρειάζονται Solr. Ο test Solr core είναι κοινός με το dev.
    monkeypatch.setattr(
        "ckan.lib.search.dispatch_by_operation", lambda *args, **kwargs: None
    )


def _add_member(org, user, role, acting_user=None):
    context = {"ignore_auth": acting_user is None}
    if acting_user:
        context["user"] = acting_user["name"]
    return helpers.call_action(
        "organization_member_create",
        context=context,
        id=org["id"],
        username=user["name"],
        role=role,
    )


def _capacity(org, user):
    member = model.Session.query(model.Member).filter_by(
        group_id=org["id"], table_id=user["id"], table_name="user",
        state="active",
    ).one()
    return member.capacity


def _can(auth_name, user, **data_dict):
    try:
        return helpers.call_auth(
            auth_name, {"user": user["name"], "model": model}, **data_dict
        )
    except toolkit.NotAuthorized:
        return False


@pytest.fixture
def setup():
    owner = factories.User()
    org_a = factories.Organization(user=owner)
    org_b = factories.Organization()
    users = {
        role: factories.User()
        for role in ("central_admin", "admin", "editor", "member", "dgo")
    }
    for role, user in users.items():
        _add_member(org_a, user, role)

    private_a = factories.Dataset(owner_org=org_a["id"], private=True)
    private_b = factories.Dataset(owner_org=org_b["id"], private=True)
    return {
        "owner": owner,
        "org_a": org_a,
        "org_b": org_b,
        "users": users,
        "private_a": private_a,
        "private_b": private_b,
    }


def test_roles_registered_with_copied_permissions():
    assert list(authz.ROLE_PERMISSIONS) == [
        "central_admin", "admin", "editor", "member", "dgo"]
    assert authz.ROLE_PERMISSIONS["central_admin"] == \
        authz.ROLE_PERMISSIONS["admin"]
    assert authz.ROLE_PERMISSIONS["dgo"] == authz.ROLE_PERMISSIONS["member"]

    roles.register_org_roles()

    assert list(authz.ROLE_PERMISSIONS) == [
        "central_admin", "admin", "editor", "member", "dgo"]
    assert set(roles.ROLE_LABELS_EL) == set(authz.ROLE_PERMISSIONS)
    assert set(roles.ROLE_LABELS_EL_LOWER) == set(authz.ROLE_PERMISSIONS)


def test_new_roles_are_stored_as_is(setup):
    org_a = setup["org_a"]
    users = setup["users"]

    assert _capacity(org_a, users["central_admin"]) == "central_admin"
    assert _capacity(org_a, users["dgo"]) == "dgo"

    org = helpers.call_action(
        "organization_show", id=org_a["id"], include_users=True)
    capacities = {u["name"]: u["capacity"] for u in org["users"]}
    assert capacities[users["central_admin"]["name"]] == "central_admin"
    assert capacities[users["dgo"]["name"]] == "dgo"


def test_unknown_role_is_rejected(setup):
    with pytest.raises(toolkit.ValidationError):
        _add_member(setup["org_a"], factories.User(), "foo")


def test_member_list_shows_new_role_labels(setup):
    org_a = setup["org_a"]
    users = setup["users"]

    members = helpers.call_action(
        "member_list", id=org_a["id"], object_type="user")
    labels = {user_id: label for user_id, _, label in members}

    assert labels[users["central_admin"]["id"]] == \
        authz.trans_role("central_admin")
    assert labels[users["dgo"]["id"]] == authz.trans_role("dgo")
    assert authz.trans_role("central_admin") != authz.trans_role("admin")
    assert authz.trans_role("dgo") != authz.trans_role("member")


def test_member_list_admin_filter_includes_central_admin(setup):
    org_a = setup["org_a"]
    users = setup["users"]

    admins = {m[0] for m in helpers.call_action(
        "member_list", id=org_a["id"], object_type="user", capacity="admin")}
    assert admins == {
        setup["owner"]["id"],
        users["admin"]["id"],
        users["central_admin"]["id"],
    }

    members = {m[0] for m in helpers.call_action(
        "member_list", id=org_a["id"], object_type="user", capacity="member")}
    assert members == {users["member"]["id"]}


def test_admin_ids_include_central_admin(setup):
    admin_ids = authz.get_group_or_org_admin_ids(setup["org_a"]["id"])
    assert setup["users"]["central_admin"]["id"] in admin_ids
    assert setup["users"]["dgo"]["id"] not in admin_ids


def test_member_roles_list_only_for_organizations():
    org_roles = [r["value"] for r in helpers.call_action(
        "member_roles_list", group_type="organization")]
    assert org_roles == ["central_admin", "admin", "editor", "member", "dgo"]

    group_roles = [r["value"] for r in helpers.call_action(
        "member_roles_list", group_type="group")]
    assert group_roles == ["admin", "member"]


def _auth_checks(setup):
    org_a = setup["org_a"]
    private_a = setup["private_a"]
    private_b = setup["private_b"]
    return [
        ("package_create", {"owner_org": org_a["id"]}),
        ("package_update", {"id": private_a["id"]}),
        ("package_delete", {"id": private_a["id"]}),
        ("package_show", {"id": private_a["id"]}),
        ("organization_update", {"id": org_a["id"]}),
        ("organization_delete", {"id": org_a["id"]}),
        ("organization_member_create", {"id": org_a["id"]}),
        ("organization_member_delete", {"id": org_a["id"]}),
        ("package_show", {"id": private_b["id"]}),
        ("package_update", {"id": private_b["id"]}),
        ("organization_update", {"id": setup["org_b"]["id"]}),
    ]


def test_central_admin_has_same_permissions_as_admin(setup):
    users = setup["users"]
    for auth_name, data_dict in _auth_checks(setup):
        assert _can(auth_name, users["central_admin"], **data_dict) == \
            _can(auth_name, users["admin"], **data_dict), auth_name


def test_dgo_has_same_permissions_as_member(setup):
    users = setup["users"]
    for auth_name, data_dict in _auth_checks(setup):
        assert _can(auth_name, users["dgo"], **data_dict) == \
            _can(auth_name, users["member"], **data_dict), auth_name


def test_expected_permissions(setup):
    users = setup["users"]
    org_a = setup["org_a"]
    private_a = setup["private_a"]
    private_b = setup["private_b"]

    central_admin = users["central_admin"]
    assert _can("package_create", central_admin, owner_org=org_a["id"])
    assert _can("package_update", central_admin, id=private_a["id"])
    assert _can("organization_member_create", central_admin, id=org_a["id"])
    assert not _can("package_show", central_admin, id=private_b["id"])

    dgo = users["dgo"]
    assert _can("package_show", dgo, id=private_a["id"])
    assert not _can("package_create", dgo, owner_org=org_a["id"])
    assert not _can("package_update", dgo, id=private_a["id"])
    assert not _can("organization_update", dgo, id=org_a["id"])
    assert not _can("organization_member_create", dgo, id=org_a["id"])
    assert not _can("package_show", dgo, id=private_b["id"])


def test_private_dataset_search_labels(setup):
    org_a = setup["org_a"]
    org_b = setup["org_b"]
    labels = get_permission_labels()

    for role in ("central_admin", "dgo"):
        user_obj = model.User.get(setup["users"][role]["name"])
        user_labels = labels.get_user_dataset_labels(user_obj)
        assert "member-%s" % org_a["id"] in user_labels
        assert "member-%s" % org_b["id"] not in user_labels


def test_activity_stream_visibility(setup):
    org_a = setup["org_a"]
    private_a = setup["private_a"]
    users = setup["users"]

    def org_stream(role):
        return auth._user_can_view_organization_activity_stream(
            {"user": users[role]["name"]}, org_a["id"])

    def dataset_stream(role):
        return auth._user_can_view_dataset_activity_stream(
            {"user": users[role]["name"]}, private_a["id"])

    assert org_stream("central_admin") and dataset_stream("central_admin")
    assert org_stream("admin") and dataset_stream("admin")
    assert not org_stream("dgo") and not dataset_stream("dgo")


def test_check_user_org_permission(app, setup):
    org_a = setup["org_a"]

    def check(role):
        token = factories.APIToken(user=setup["users"][role]["name"])
        response = app.post(
            "/api/3/action/check_user_org_permission",
            json={"organization_id": org_a["id"]},
            headers={"Authorization": token["token"]},
        )
        return response.json["result"]["success"]

    assert check("central_admin")
    assert check("admin")
    assert check("editor")
    assert not check("dgo")
    assert not check("member")


def test_user_organization_capacity_stays_compatible(app, setup):
    org_a = setup["org_a"]
    sysadmin = factories.Sysadmin()
    token = factories.APIToken(user=sysadmin["name"])

    for role, sub, expected_capacity in (
        ("central_admin", "sub-central", "admin"),
        ("dgo", "sub-dgo", "member"),
        ("editor", "sub-editor", "editor"),
    ):
        user_obj = model.User.get(setup["users"][role]["name"])
        user_obj.plugin_extras = {"sub": sub}
        model.repo.commit()

        response = app.post(
            "/api/3/action/user_organization_capacity",
            json={"org_id": org_a["id"], "sub": sub},
            headers={"Authorization": token["token"]},
        )
        result = response.json["result"]
        assert result["is_member"]
        assert result["capacity"] == expected_capacity
        assert result["role"] == role


def test_role_changes_by_another_admin(setup):
    org_a = setup["org_a"]
    owner = setup["owner"]
    user = setup["users"]["admin"]

    _add_member(org_a, user, "central_admin", acting_user=owner)
    assert _capacity(org_a, user) == "central_admin"

    _add_member(org_a, user, "admin", acting_user=owner)
    assert _capacity(org_a, user) == "admin"


@pytest.mark.parametrize("new_role", ["admin", "editor", "member", "dgo"])
def test_central_admin_cannot_change_own_role(setup, new_role):
    org_a = setup["org_a"]
    central_admin = setup["users"]["central_admin"]

    with pytest.raises(toolkit.NotAuthorized):
        _add_member(org_a, central_admin, new_role, acting_user=central_admin)
    assert _capacity(org_a, central_admin) == "central_admin"


def test_admin_cannot_make_self_central_admin(setup):
    org_a = setup["org_a"]
    admin = setup["users"]["admin"]

    with pytest.raises(toolkit.NotAuthorized):
        _add_member(org_a, admin, "central_admin", acting_user=admin)
    assert _capacity(org_a, admin) == "admin"


def test_dgo_cannot_promote_self(setup):
    org_a = setup["org_a"]
    dgo = setup["users"]["dgo"]

    with pytest.raises(toolkit.NotAuthorized):
        _add_member(org_a, dgo, "admin", acting_user=dgo)
    assert _capacity(org_a, dgo) == "dgo"


def test_add_cascade_equivalents():
    cfg = {roles.CASCADE_CONFIG: ["admin"]}
    roles.add_cascade_equivalents(cfg)
    assert cfg[roles.CASCADE_CONFIG] == ["admin", "central_admin"]

    cfg = {roles.CASCADE_CONFIG: ["admin", "member"]}
    roles.add_cascade_equivalents(cfg)
    roles.add_cascade_equivalents(cfg)
    assert cfg[roles.CASCADE_CONFIG] == [
        "admin", "member", "central_admin", "dgo"]

    cfg = {roles.CASCADE_CONFIG: []}
    roles.add_cascade_equivalents(cfg)
    assert cfg[roles.CASCADE_CONFIG] == []


def test_cascade_config_includes_central_admin():
    cascade = authz.check_config_permission("roles_that_cascade_to_sub_groups")
    assert "admin" in cascade
    assert "central_admin" in cascade
    assert "dgo" not in cascade


@pytest.mark.parametrize("role", ["admin", "central_admin"])
def test_parent_membership_cascades_to_child_org(role):
    user = factories.User()
    parent = factories.Organization()
    child = factories.Organization()
    helpers.call_action(
        "member_create",
        id=child["id"],
        object=parent["id"],
        object_type="group",
        capacity="parent",
    )
    _add_member(parent, user, role)

    assert authz.has_user_permission_for_group_or_org(
        child["id"], user["name"], "create_dataset")
    assert _can("organization_update", user, id=child["id"])

    org_ids = {org["id"] for org in helpers.call_action(
        "organization_list_for_user",
        context={"user": user["name"]},
        permission="create_dataset",
    )}
    assert org_ids == {parent["id"], child["id"]}


def _capture_core_invite_email(monkeypatch):
    sent = []

    def fake_mail_user(recipient, subject, body, *args, **kwargs):
        sent.append(body)

    monkeypatch.setattr("ckan.lib.mailer.mail_user", fake_mail_user)
    return sent


def _capture_data_gov_gr_email(monkeypatch):
    sent = []
    monkeypatch.setattr(
        dgg_actions, "mail_recipient", lambda **kwargs: sent.append(kwargs))
    return sent


@pytest.mark.ckan_config("ckanext.keycloak.enable_ckan_internal_login", "true")
@pytest.mark.usefixtures("with_request_context")
@pytest.mark.parametrize("role", ["central_admin", "dgo"])
def test_core_invite_with_new_role(setup, monkeypatch, role):
    sent = _capture_core_invite_email(monkeypatch)

    user = helpers.call_action(
        "user_invite",
        email="invite-%s@example.org" % role,
        group_id=setup["org_a"]["id"],
        role=role,
    )

    assert _capacity(setup["org_a"], user) == role
    assert len(sent) == 1
    assert authz.trans_role(role) in sent[0]


@pytest.mark.ckan_config("ckanext.keycloak.enable_ckan_internal_login", "false")
@pytest.mark.ckan_config(
    "ckanext.data_gov_gr.user_invite_method", "waiting_keycloak")
@pytest.mark.ckan_config(
    "ckanext.data_gov_gr.user_invite.waiting_keycloak.send_email", "true")
@pytest.mark.ckan_config(
    "ckanext.data_gov_gr.user.allow_any_character_in_username", "true")
@pytest.mark.usefixtures("with_request_context")
@pytest.mark.parametrize("role", ["central_admin", "dgo"])
def test_waiting_keycloak_invite_with_new_role(setup, monkeypatch, role):
    sent = _capture_data_gov_gr_email(monkeypatch)

    user = helpers.call_action(
        "user_invite",
        email="invite-%s@example.org" % role,
        group_id=setup["org_a"]["id"],
        role=role,
    )

    assert _capacity(setup["org_a"], user) == role
    assert len(sent) == 1
    assert roles.ROLE_LABELS_EL_LOWER[role] in sent[0]["body"]


@pytest.mark.ckan_config("ckanext.keycloak.enable_ckan_internal_login", "false")
@pytest.mark.ckan_config("ckanext.data_gov_gr.user_invite_method", "notify")
@pytest.mark.usefixtures("with_request_context")
@pytest.mark.parametrize("role", ["central_admin", "dgo"])
def test_notify_invite_with_new_role(setup, monkeypatch, role):
    sent = _capture_data_gov_gr_email(monkeypatch)

    helpers.call_action(
        "user_invite",
        email="invite-%s@example.org" % role,
        group_id=setup["org_a"]["id"],
        role=role,
    )

    assert len(sent) == 1
    assert roles.ROLE_LABELS_EL_LOWER[role] in sent[0]["body"]


def test_revert_org_roles(setup):
    org_a = setup["org_a"]
    users = setup["users"]

    changes = commands.revert_org_roles(apply_changes=False)
    assert {(c["user"], c["current_role"], c["new_role"]) for c in changes} == {
        (users["central_admin"]["name"], "central_admin", "admin"),
        (users["dgo"]["name"], "dgo", "member"),
    }
    assert _capacity(org_a, users["central_admin"]) == "central_admin"

    commands.revert_org_roles(apply_changes=True)

    assert _capacity(org_a, users["central_admin"]) == "admin"
    assert _capacity(org_a, users["dgo"]) == "member"
    assert commands.revert_org_roles(apply_changes=False) == []
