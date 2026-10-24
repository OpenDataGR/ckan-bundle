"""Role handling across all CSV invite and synchronization flows."""

from collections import OrderedDict
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import ckan.authz as authz
from flask import Flask
import pytest

from ckanext.csvinvite import views


CENTRAL_ADMIN = "central_admin"
DGO = "dgo"


@pytest.fixture(autouse=True)
def registered_new_roles(monkeypatch):
    """Model the registry exposed by data_gov_gr without coupling unit tests."""
    permissions = OrderedDict(authz.ROLE_PERMISSIONS)
    permissions[CENTRAL_ADMIN] = list(permissions["admin"])
    permissions[DGO] = list(permissions["member"])
    monkeypatch.setattr(authz, "ROLE_PERMISSIONS", permissions)


@pytest.fixture
def request_app(monkeypatch):
    """Minimal request context for testing view flows without Redis or a DB."""
    app = Flask(__name__)
    app.secret_key = "csvinvite-role-tests"

    stored = {}
    monkeypatch.setattr(
        views.toolkit,
        "c",
        SimpleNamespace(user="tester", userobj=SimpleNamespace(sysadmin=True)),
    )
    monkeypatch.setattr(views, "_feature_enabled", lambda _name: True)
    monkeypatch.setattr(views, "_is_org_admin", lambda _context, _org: True)
    monkeypatch.setattr(views, "_require_sysadmin", lambda _context: None)
    monkeypatch.setattr(views, "is_redis_available", lambda: True)
    monkeypatch.setattr(views.magic, "from_buffer", lambda *_a, **_kw: "text/csv")
    monkeypatch.setattr(views, "_csvinvite_new_token", lambda: "role-test-token")
    monkeypatch.setattr(views, "_fresh_action_context", lambda context: dict(context))
    monkeypatch.setattr(
        views,
        "_csvinvite_cache_set",
        lambda key, payload, ttl_seconds=views.CSVINVITE_BULK_ORG_SYNC_TTL_SECONDS:
            stored.update({key: payload}),
    )
    monkeypatch.setattr(
        views.toolkit,
        "redirect_to",
        lambda endpoint, **_kwargs: endpoint,
    )
    return app, stored


@pytest.mark.parametrize(
    ("raw_role", "expected"),
    [
        (CENTRAL_ADMIN, CENTRAL_ADMIN),
        (DGO, DGO),
        ("Central Administrator", CENTRAL_ADMIN),
        ("Data Governance Officer (DGO)", DGO),
        ("Κεντρικός Διαχειριστής", CENTRAL_ADMIN),
        ("Υπεύθυνος Χρήσης Δεδομένων (ΥΧΔ - DGO)", DGO),
        ("Υπεύθυνος Χρήσης Δεδομένων", DGO),
        ("ΥΧΔ - DGO", DGO),
        ("ΥΧΔ", DGO),
        ("ADMIN", "admin"),
        ("Συντάκτης", "editor"),
        ("Μέλος", "member"),
        ("", "member"),
        (None, "member"),
    ],
)
def test_normalize_role_aliases(raw_role, expected):
    assert views._normalize_role(raw_role) == expected


def test_unknown_role_keeps_existing_member_fallback():
    assert views._normalize_role("unknown-role") == "member"


def test_bulk_org_invite_parser_accepts_new_roles_and_greek_aliases():
    rows, errors = views._parse_bulk_org_invite_csv(
        "org,email,role\n"
        "org-a,central@example.gr,central_admin\n"
        "org-b,dgo@example.gr,Υπεύθυνος Χρήσης Δεδομένων (ΥΧΔ - DGO)\n"
    )

    assert errors == []
    assert [row["role"] for row in rows] == [CENTRAL_ADMIN, DGO]


def test_single_org_sync_parser_accepts_new_roles_and_greek_aliases():
    rows, errors = views._parse_sync_csv(
        "username,email,role\n"
        "central,,Κεντρικός Διαχειριστής\n"
        ",dgo@example.gr,dgo\n"
    )

    assert errors == []
    assert [row["role"] for row in rows] == [CENTRAL_ADMIN, DGO]


def test_bulk_org_sync_parser_accepts_new_roles_and_greek_aliases():
    rows, errors = views._parse_bulk_org_sync_csv(
        "org,username,email,role\n"
        "org-a,central,,central_admin\n"
        "org-b,,dgo@example.gr,Υπεύθυνος Χρήσης Δεδομένων (ΥΧΔ - DGO)\n"
    )

    assert errors == []
    assert [row["role"] for row in rows] == [CENTRAL_ADMIN, DGO]


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Κεντρικός Διαχειριστής", CENTRAL_ADMIN),
        ("Υπεύθυνος Χρήσης Δεδομένων (ΥΧΔ - DGO)", DGO),
        ("Central Administrator", CENTRAL_ADMIN),
        ("Data Governance Officer (DGO)", DGO),
    ],
)
def test_member_list_labels_map_back_to_capacities(label, expected):
    assert views._capacity_from_member_list_item(("user-id", "user", label)) == expected


def _member(username, role, email=None):
    return {
        "username": username,
        "email": email or f"{username}@example.gr",
        "role": role,
        "sysadmin": False,
        "state": "active",
    }


def _sync_row(line, username, role):
    return {
        "line": line,
        "username": username,
        "email": "",
        "role": role,
    }


def test_sync_plan_leaves_matching_new_roles_unchanged():
    existing = [
        _member("central", CENTRAL_ADMIN),
        _member("dgo-user", DGO),
    ]
    csv_rows = [
        _sync_row(2, "central", CENTRAL_ADMIN),
        _sync_row(3, "dgo-user", DGO),
    ]

    plan = views._plan_full_sync({}, "org-a", existing, {}, {}, csv_rows)

    assert plan["role_updates"] == []
    assert {item["role"] for item in plan["unchanged"]} == {
        CENTRAL_ADMIN,
        DGO,
    }


@pytest.mark.parametrize(
    ("current_role", "new_role"),
    [
        ("admin", CENTRAL_ADMIN),
        ("member", DGO),
        (CENTRAL_ADMIN, "admin"),
        (DGO, "member"),
    ],
)
def test_sync_plan_detects_role_changes(current_role, new_role):
    existing = [_member("role-user", current_role)]
    csv_rows = [_sync_row(2, "role-user", new_role)]

    plan = views._plan_full_sync({}, "org-a", existing, {}, {}, csv_rows)

    assert len(plan["role_updates"]) == 1
    assert plan["role_updates"][0]["member"]["role"] == current_role
    assert plan["role_updates"][0]["new_role"] == new_role


def test_sync_plan_preserves_new_roles_for_creations_and_pending_invites(
    monkeypatch,
):
    existing_user = SimpleNamespace(
        id="existing-id",
        name="central",
        email="central@example.gr",
        state="active",
        sysadmin=False,
    )

    def find_user(username=None, email=None):
        if username == "central" or email == "central@example.gr":
            return existing_user
        return None

    monkeypatch.setattr(views, "_db_find_user", find_user)
    csv_rows = [
        _sync_row(2, "central", CENTRAL_ADMIN),
        {
            "line": 3,
            "username": "",
            "email": "new-dgo@example.gr",
            "role": DGO,
        },
    ]

    plan = views._plan_full_sync({}, "org-a", [], {}, {}, csv_rows)

    assert plan["creations"][0]["role"] == CENTRAL_ADMIN
    assert plan["pending_invites"][0]["role"] == DGO


def test_apply_full_sync_forwards_new_roles_to_ckan_action(monkeypatch):
    calls = []

    def get_action(name):
        def action(_context, data_dict):
            calls.append((name, data_dict))
        return action

    monkeypatch.setattr(views.toolkit, "get_action", get_action)
    monkeypatch.setattr(views, "_fresh_action_context", lambda context: dict(context))
    plan = {
        "removals": [],
        "role_updates": [
            {"member": {"username": "central"}, "new_role": CENTRAL_ADMIN},
        ],
        "creations": [
            {"username": "dgo-user", "role": DGO},
        ],
    }

    result = views._apply_full_sync({}, "org-a", plan, remove_missing=False)

    assert result == {"removed": 0, "updated": 1, "created": 1}
    assert calls == [
        (
            "organization_member_create",
            {"id": "org-a", "username": "central", "role": CENTRAL_ADMIN},
        ),
        (
            "organization_member_create",
            {"id": "org-a", "username": "dgo-user", "role": DGO},
        ),
    ]


@pytest.mark.parametrize("role", [CENTRAL_ADMIN, DGO])
def test_call_user_invite_forwards_new_role(monkeypatch, role):
    calls = []
    monkeypatch.setattr(
        views.toolkit,
        "get_action",
        lambda name: lambda context, data: calls.append((name, context, data)),
    )

    views._call_user_invite({"user": "admin"}, "org-a", "user@example.gr", role)

    assert calls == [
        (
            "user_invite",
            {"user": "admin"},
            {
                "email": "user@example.gr",
                "group_id": "org-a",
                "role": role,
                "send_email": False,
            },
        )
    ]


def test_import_members_dry_run_preserves_new_roles(
    request_app,
    monkeypatch,
):
    app, stored = request_app
    monkeypatch.setattr(
        views.toolkit,
        "get_action",
        lambda name: lambda _context, _data: {"id": "org-a", "name": "org-a"},
    )
    monkeypatch.setattr(
        views,
        "_call_user_invite",
        lambda *_args, **_kwargs: pytest.fail("dry-run must not invite users"),
    )
    csv_data = (
        "email,role\n"
        "central@example.gr,central_admin\n"
        "dgo@example.gr,Υπεύθυνος Χρήσης Δεδομένων (ΥΧΔ - DGO)\n"
    ).encode()

    with app.test_request_context(
        "/organization/org-a/members/import",
        method="POST",
        data={"file": (BytesIO(csv_data), "roles.csv"), "dry_run": "1"},
    ):
        views.import_members_post("org-a")

    payload = next(iter(stored.values()))
    assert payload["results"]["would_invite"] == 2
    assert [row["role"] for row in payload["results"]["rows"]] == [
        CENTRAL_ADMIN,
        DGO,
    ]


def test_import_members_apply_forwards_new_roles(request_app, monkeypatch):
    app, stored = request_app
    invited_roles = []
    monkeypatch.setattr(
        views.toolkit,
        "get_action",
        lambda name: lambda _context, _data: {"id": "org-a", "name": "org-a"},
    )
    monkeypatch.setattr(
        views,
        "_call_user_invite",
        lambda _context, _org, _email, role: invited_roles.append(role),
    )
    csv_data = (
        "email,role\n"
        "central@example.gr,Κεντρικός Διαχειριστής\n"
        "dgo@example.gr,dgo\n"
    ).encode()

    with app.test_request_context(
        "/organization/org-a/members/import",
        method="POST",
        data={"file": (BytesIO(csv_data), "roles.csv")},
    ):
        views.import_members_post("org-a")

    payload = next(iter(stored.values()))
    assert invited_roles == [CENTRAL_ADMIN, DGO]
    assert payload["results"]["invited"] == 2


def test_single_org_sync_dry_run_passes_new_roles_to_planner(
    request_app,
    monkeypatch,
):
    app, stored = request_app
    planned_rows = []
    empty_plan = {
        "removals": [],
        "role_updates": [],
        "creations": [],
        "pending_invites": [],
        "missing_users": [],
        "protected_skips": [],
        "unchanged": [],
        "warnings": [],
    }
    monkeypatch.setattr(
        views.toolkit,
        "get_action",
        lambda name: lambda _context, _data: {"id": "org-a", "name": "org-a"},
    )
    monkeypatch.setattr(views, "_build_org_member_index", lambda *_args: ([], {}, {}))

    def plan(_context, _org, _existing, _by_username, _by_email, csv_rows):
        planned_rows.extend(csv_rows)
        return empty_plan

    monkeypatch.setattr(views, "_plan_full_sync", plan)
    monkeypatch.setattr(
        views,
        "_apply_full_sync",
        lambda *_args, **_kwargs: pytest.fail("dry-run must not apply changes"),
    )
    csv_data = (
        "username,email,role\n"
        "central,,central_admin\n"
        ",dgo@example.gr,ΥΧΔ\n"
    ).encode()

    with app.test_request_context(
        "/organization/org-a/members/sync",
        method="POST",
        data={"file": (BytesIO(csv_data), "roles.csv"), "dry_run": "true"},
    ):
        views.sync_members_post("org-a")

    assert [row["role"] for row in planned_rows] == [CENTRAL_ADMIN, DGO]
    payload = next(iter(stored.values()))
    assert payload["dry_run"] is True
    assert payload["applied"] is None


def test_bulk_org_invite_forwards_new_roles(request_app, monkeypatch):
    app, stored = request_app
    invited_roles = []

    def get_action(name):
        assert name == "organization_show"
        return lambda _context, data: {"id": f"id-{data['id']}"}

    monkeypatch.setattr(views.toolkit, "get_action", get_action)
    monkeypatch.setattr(
        views,
        "_call_user_invite",
        lambda _context, _org, _email, role: invited_roles.append(role),
    )
    csv_data = (
        "org,email,role\n"
        "org-a,central@example.gr,central_admin\n"
        "org-b,dgo@example.gr,ΥΧΔ - DGO\n"
    ).encode()

    with app.test_request_context(
        "/ckan-admin/users/bulk-invite",
        method="POST",
        data={"file": (BytesIO(csv_data), "roles.csv")},
    ):
        views.admin_bulk_org_invite_post()

    payload = next(iter(stored.values()))
    assert invited_roles == [CENTRAL_ADMIN, DGO]
    assert payload["results"]["invited"] == 2


def test_bulk_org_sync_dry_run_passes_new_roles_to_each_plan(
    request_app,
    monkeypatch,
):
    app, stored = request_app
    roles_by_org = {}

    def get_action(name):
        assert name == "organization_show"
        return lambda _context, data: {
            "id": f"id-{data['id']}",
            "name": data["id"],
        }

    monkeypatch.setattr(views.toolkit, "get_action", get_action)
    monkeypatch.setattr(views, "_build_org_member_index", lambda *_args: ([], {}, {}))

    def plan(_context, org_id, _existing, _by_username, _by_email, csv_rows):
        roles_by_org[org_id] = [row["role"] for row in csv_rows]
        return {
            "removals": [],
            "role_updates": [],
            "creations": [dict(row, state="active") for row in csv_rows],
            "pending_invites": [],
            "missing_users": [],
            "protected_skips": [],
            "unchanged": [],
            "warnings": [],
        }

    monkeypatch.setattr(views, "_plan_full_sync", plan)
    monkeypatch.setattr(
        views,
        "_apply_full_sync",
        lambda *_args, **_kwargs: pytest.fail("dry-run must not apply changes"),
    )
    csv_data = (
        "org,username,email,role\n"
        "org-a,central,,Κεντρικός Διαχειριστής\n"
        "org-b,,dgo@example.gr,dgo\n"
    ).encode()

    with app.test_request_context(
        "/ckan-admin/users/bulk-sync",
        method="POST",
        data={"file": (BytesIO(csv_data), "roles.csv"), "dry_run": "yes"},
    ):
        views.admin_bulk_org_sync_post()

    assert roles_by_org == {
        "id-org-a": [CENTRAL_ADMIN],
        "id-org-b": [DGO],
    }
    payload = next(iter(stored.values()))
    assert [row["new_role"] for row in payload["export_rows"]] == [
        CENTRAL_ADMIN,
        DGO,
    ]


def test_bulk_org_sync_export_rows_preserve_new_roles():
    report = {
        "orgs": [
            {
                "org_ref": "org-a",
                "org_id": "org-id",
                "org_name": "Organization A",
                "plan": {
                    "removals": [],
                    "role_updates": [
                        {
                            "member": _member("admin-user", "admin"),
                            "new_role": CENTRAL_ADMIN,
                        }
                    ],
                    "unchanged": [_member("dgo-user", DGO)],
                    "creations": [],
                    "pending_invites": [],
                    "protected_skips": [],
                },
            }
        ]
    }

    rows = views._bulk_org_sync_plan_to_export_rows(report)

    assert rows[0]["current_role"] == "admin"
    assert rows[0]["new_role"] == CENTRAL_ADMIN
    assert rows[1]["current_role"] == DGO


@pytest.mark.parametrize(
    "template",
    [
        "import_members.html",
        "sync_members.html",
        "admin_bulk_org_invite.html",
        "admin_bulk_org_sync.html",
    ],
)
def test_role_help_templates_document_new_roles(template):
    template_path = Path(views.__file__).parent / "templates" / "csvinvite" / template
    content = template_path.read_text(encoding="utf-8")

    assert CENTRAL_ADMIN in content
    assert DGO in content


def test_shared_role_help_documents_roles_and_equivalent_permissions():
    template_path = (
        Path(views.__file__).parent
        / "templates"
        / "csvinvite"
        / "snippets"
        / "roles_permissions.html"
    )
    content = template_path.read_text(encoding="utf-8")

    assert "Member" in content
    assert "Editor" in content
    assert "Admin" in content
    assert CENTRAL_ADMIN in content
    assert DGO in content
    assert "same permissions as admin" in content
    assert "same permissions as member" in content


@pytest.mark.parametrize(
    "template",
    [
        "admin_user_management.html",
        "snippets/bulk_invite_sidebar.html",
        "snippets/bulk_sync_sidebar.html",
    ],
)
def test_role_help_consumers_include_shared_role_help(template):
    template_path = (
        Path(views.__file__).parent
        / "templates"
        / "csvinvite"
        / template
    )
    content = template_path.read_text(encoding="utf-8")

    assert "{% include 'csvinvite/snippets/roles_permissions.html' %}" in content


def test_data_gov_gr_role_registry_integrates_with_normalizer(monkeypatch):
    data_gov_roles = pytest.importorskip("ckanext.data_gov_gr.roles")
    monkeypatch.setattr(authz, "_trans_functions", dict(authz._trans_functions))
    monkeypatch.setattr(
        authz,
        "get_group_or_org_admin_ids",
        authz.get_group_or_org_admin_ids,
    )

    data_gov_roles.register_org_roles()

    assert views._normalize_role(CENTRAL_ADMIN) == CENTRAL_ADMIN
    assert views._normalize_role(DGO) == DGO
