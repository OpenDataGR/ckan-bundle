# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added (OD-857)
- Configurable queue (`ckanext.downloadall.queue`); jobs are queued after the
  database commit.
- Optional Redis coordination for coalescing DownloadAll jobs for the same
  dataset across requests and workers (`ckanext.downloadall.dedup_strategy =
  redis`, `ckanext.downloadall.redis_lock_ttl`), from the
  `feature/downloadall-redis-coalescing` branch. The default remains
  per-request deduplication (`request_cache`); enqueueing never lists the full
  CKAN job queue.
- `ckanext.downloadall.hvd_only`, resource exclusion by format, name pattern or
  `downloadall_exclude=true` (nothing is excluded by default, as before).
- `downloadall-manifest.json` with included / excluded / failed resources.
- Zip fingerprint: the "Download all" button is disabled while the zip is stale.
  If a rebuild fails, the previous zip stays available
  (`downloadall_attempted_fingerprint`).
- Timeouts, retries, size limits and a time limit before the job timeout.
- `downloadall cleanup` (dry-run by default), `update-all-zips --dry-run` and
  `update-all-zips --retry-failed` (daily cron: missing, out of date or with
  failed resources).

### Changed (OD-857), Redis coordination
- A change made during a job that fails, or that has no time left for another
  iteration, queues a new job.
- The lock lifetime is at least `job_timeout` + 300 seconds.
- With `redis`, every change is marked dirty, also within the same request.

### Changed (OD-857)
- Resources are streamed to a temporary file instead of memory.
- Filenames keep or add a proper extension and are made unique.
- The exact blob of the previous zip is deleted after a successful rebuild,
  once the new blob is found in the storage with the right size.

### Fixed (OD-857)
- `KeyError: 'format'` for resources without a filename in the URL and without
  a format, which failed the whole job.
- `JobTimeoutException` was swallowed, so jobs ran until SIGKILL.
- Jobs for deleted datasets no longer fail; draft and deleted datasets get no
  zip.
- No zip with only metadata when no resource can go into it.
- An unreadable local upload is a failed resource, not a failed job.
- A non-boolean `downloadall_exclude` value no longer breaks the dataset page.

### Fixed (OD-857, code review)
- Two jobs finishing together no longer create two zip resources: saving the
  zip takes a PostgreSQL advisory lock per dataset and re-reads the current
  zip. With duplicate zips, the page, the job and `cleanup` all use the first
  one in resource order.
- The zip job and `update-all-zips --synchronous` read the dataset afresh, so
  a build no longer writes old metadata over edits made in the meantime.
- Any unexpected error while downloading a resource fails only that resource
  (the RQ timeout still stops the job).
- A server that sends data very slowly is cut at the time limit instead of the
  job timeout.
- A successful build clears `downloadall_attempted_fingerprint`.
- Redis coordination: the lock is released after a Redis error (with a few
  quick retries); another iteration starts only if it fits in the time left;
  `update-all-zips --retry-failed` reaches a job that is already pending.
- `request_cache`: every database commit queues a job, so a second commit in
  the same request is not lost.
- `update-all-zips` carries on after an error in one dataset and exits with a
  non-zero status if any dataset failed.
- `cleanup --apply` re-reads the zip's current file before deleting a blob.
- Third code review and the handoff (§3): before saving, the job re-reads the
  dataset under the lock; it does not save for a dataset that is no longer
  eligible, does not overwrite a newer zip, and queues one more processing if
  the dataset changed during the build. `downloadall_cleanup_pending` is
  written on its own, without rewriting the zip resource.
- `update-all-zips --retry-failed`: zips without a fingerprint (before this
  version) are not rebuilt automatically; failed builds of a dataset without a
  zip (kept in Redis) and failed rebuilds of the current version count towards
  `retry_failed_limit`; only forced rebuilds count as retries.
- The licence title and URL are left out of the `datapackage.json` hash too.
- Chained `package_update` / `resource_delete`: when a caller (e.g. a
  harvester or API script) updates a dataset with a resource list that omits
  the existing DownloadAll zip resource, the zip resource is preserved on the
  same id (avoiding a disappearing button and orphaned cloud blobs) and a
  forced rebuild is queued after commit without counting towards
  `downloadall_retries`. Explicit `resource_delete` and partial updates
  without `resources` are unaffected.
- All zip resources are removed when a dataset loses its zip; an uploader error
  fails only that resource; the time margin of a short `job_timeout` is at most
  half of it; `update-zip`/`update-all-zips --synchronous` have a time limit.
- The fingerprint no longer includes `license_title` and `license_url`
  (derived from `license_id`). The translated licence title differs between
  the search index and the database, so a zip showed as stale right after its
  first build and was rebuilt although nothing had changed.
- `update-all-zips --retry-failed` rebuilds a zip only for temporary resource
  failures (timeout, connection error, HTTP 5xx or 429), at most
  `ckanext.downloadall.retry_failed_limit` (default 3) times per dataset
  version; permanent failures are tried again when the dataset changes.
- Private datasets get no zip: the worker has no credentials for the resources
  that CKAN itself serves (e.g. datastore dumps), which always failed with 403.
  The zip is built when the dataset is made public.

### Removed (OD-857)
- The Python 2 / nose tests (`test_plugin.py`, `test_tasks.py`,
  `test_action.py`), which could no longer run and targeted removed functions.
  The behaviour they covered and the new tests did not (datastore schema and
  extra dataset fields in `datapackage.json`, local uploads, jobs after a
  resource deletion or `datastore_create`) is now in `test_od857_ported.py`.
  The tests run with pytest (see README).

### Fixed
- Fixed issue with incorrect file modification dates (01/01/1980) in ZIP archives by preserving original timestamps for local resources, using Last-Modified headers for downloaded resources, and current time for dynamically generated files

## [0.1.0] - 2019-11-12

### Added
- Config option added: ckanext.downloadall.dataset_fields_to_add_to_datapackage for including custom fields from the dataset in the datapackage.json

### Fixed
- Fixed home page exception KeyError: 'resources'

## [0.0.2] - 2019-06-30
### Added
- Command-line interface.
- Schema added to the datapackage.json if a resource's Data Dictionary is completed.

### Changed
- Dependencies moved to setup.py's install_requires, for convenience during install.

### Fixed
- Fixed exception when non-download-all jobs are put on the CKAN background task queue.
- Fixed position of the "Download all" button to avoid overlapping bottom edge when no dataset.notes.
- Zip resource is not now shown in the sidebar resources on the resource preview page.
- Zip format is not now shown in the search facets for the Download All zip.
- Fix updating the zip when changes are made to the core dataset metadata (e.g. dataset title).

## [0.0.1] - 2019-05-27 - Initial release
### Added
- Generates a zip when a resource URL changes
- Zip contains resources and basic datapackage.json
- 'Download all' button placed on the dataset page
