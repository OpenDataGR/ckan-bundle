from __future__ import annotations

import logging

import ckan.lib.search as search
import ckan.model as model
from ckan.logic import NotFound


log = logging.getLogger(__name__)


def reindex_packages_for_tag_rename(
    package_ids: list[str],
    old_name: str,
    new_name: str,
) -> None:
    total = len(package_ids)
    failed_packages: list[str] = []
    skipped_packages: list[str] = []
    log.info(
        "manage_tags reindex job started for rename '%s' -> '%s' (%s packages)",
        old_name,
        new_name,
        total,
    )

    try:
        for index, package_id in enumerate(package_ids, start=1):
            try:
                search.rebuild(package_id)
            except NotFound:
                model.Session.rollback()
                skipped_packages.append(package_id)
                log.warning(
                    "Skipping search rebuild for missing package id '%s' after tag rename '%s' -> '%s'",
                    package_id,
                    old_name,
                    new_name,
                )
            except Exception:
                # Καθαρίζει το κοινό session αν κάποιο rebuild αφήσει failed
                # transaction state, ώστε η υπόλοιπη δουλειά να συνεχίσει.
                model.Session.rollback()
                failed_packages.append(package_id)
                log.exception(
                    "Failed to rebuild search index for package id '%s' after tag rename '%s' -> '%s'",
                    package_id,
                    old_name,
                    new_name,
                )

            if index % 100 == 0 or index == total:
                log.info(
                    "manage_tags reindex job progress for rename '%s' -> '%s': %s/%s (skipped=%s, failed=%s)",
                    old_name,
                    new_name,
                    index,
                    total,
                    len(skipped_packages),
                    len(failed_packages),
                )

        if failed_packages:
            preview = u", ".join(failed_packages[:10])
            if len(failed_packages) > 10:
                preview = u"{} ...".format(preview)
            raise RuntimeError(
                "manage_tags reindex job failed for {failed}/{total} packages after rename "
                "'{old}' -> '{new}': {packages}".format(
                    failed=len(failed_packages),
                    total=total,
                    old=old_name,
                    new=new_name,
                    packages=preview,
                )
            )
    finally:
        try:
            model.Session.remove()
        except Exception:
            log.exception(
                "manage_tags reindex job failed to remove SQLAlchemy session after rename '%s' -> '%s'",
                old_name,
                new_name,
            )

    log.info(
        "manage_tags reindex job completed for rename '%s' -> '%s' (%s packages, skipped=%s)",
        old_name,
        new_name,
        total,
        len(skipped_packages),
    )


def rebuild_search_index(clear: bool = False) -> None:
    log.info(
        "manage_tags full rebuild job started (clear=%s)",
        clear,
    )
    try:
        search.rebuild(clear=clear, quiet=True, force=False)
    except Exception:
        log.exception(
            "manage_tags full rebuild job failed (clear=%s)",
            clear,
        )
        raise
    finally:
        try:
            model.Session.remove()
        except Exception:
            log.exception(
                "manage_tags full rebuild job failed to remove SQLAlchemy session"
            )

    log.info(
        "manage_tags full rebuild job completed (clear=%s)",
        clear,
    )
