import pytest

from ckan import model
from ckanext.pages.db import Page


@pytest.fixture
def clean_db(reset_db, migrate_db_for):
    reset_db()
    migrate_db_for("pages")


@pytest.fixture
def add_page():
    created_pages = []

    def _add_page(**values):
        page = Page(
            title=values.pop("title", "Test page"),
            name=values.pop("name", "test-page"),
            content=values.pop("content", ""),
            private=values.pop("private", False),
            page_type=values.pop("page_type", "page"),
            extras=values.pop("extras", "{}"),
            revisions=values.pop("revisions", {}),
            **values,
        )
        model.Session.add(page)
        model.Session.commit()
        created_pages.append(page)
        return page

    yield _add_page

    if created_pages:
        model.Session.query(Page).delete()
        model.Session.commit()
