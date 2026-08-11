import logging
from urllib.parse import urlencode

from flask import Blueprint, make_response, request as flask_request
from ckan.common import config, current_user
from ckan.lib.base import abort, render
from ckan.plugins import toolkit

from ckanext.hvd_validator.auth import user_can_access_hvd_validator
from ckanext.hvd_validator.validator import (
    validate_from_file,
    validate_from_name,
    validate_from_url,
)

log = logging.getLogger(__name__)

blueprint = Blueprint("hvd_validator", __name__)

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {".rdf", ".ttl", ".xml", ".jsonld", ".json-ld", ".n3", ".nt"}
URL_INPUT_ENABLED_CONFIG = "ckanext.hvd_validator.input.url.enabled"
FILE_INPUT_ENABLED_CONFIG = "ckanext.hvd_validator.input.file.enabled"


def url_input_enabled():
    return toolkit.asbool(config.get(URL_INPUT_ENABLED_CONFIG, False))


def file_input_enabled():
    return toolkit.asbool(config.get(FILE_INPUT_ENABLED_CONFIG, False))


def current_user_context():
    return {
        "user": current_user.name,
        "auth_user_obj": current_user,
    }


def _render_validator_page(extra_vars):
    response = make_response(render("hvd_validator/validate.html", extra_vars))
    response.headers["Cache-Control"] = "private, no-cache"
    return response


@blueprint.route("/hvd-validator", methods=["GET", "POST"])
def validate_page():
    if not current_user.is_authenticated:
        return toolkit.redirect_to(
            "user.login",
            came_from=flask_request.full_path,
        )

    if not user_can_access_hvd_validator(current_user):
        abort(403, toolkit._("User not authorized to view page"))

    extra_vars = {
        "result": None,
        "error": None,
        "input_mode": None,
        "input_value": "",
        "url_input_enabled": url_input_enabled(),
        "file_input_enabled": file_input_enabled(),
    }

    if flask_request.method == "GET":
        input_mode = flask_request.args.get("input_mode", "").strip()
        name = flask_request.args.get("dataset_name", "").strip()

        if input_mode == "name" or name:
            extra_vars["input_mode"] = "name"
            extra_vars["input_value"] = name
            try:
                if not name:
                    raise ValueError(toolkit._("Please enter a dataset name or UUID."))
                extra_vars["result"] = validate_from_name(
                    name,
                    current_user_context(),
                )
            except Exception as exc:
                log.warning("HVD validation error: %s", exc)
                extra_vars["error"] = str(exc)

        return _render_validator_page(extra_vars)

    if flask_request.method == "POST":
        input_mode = flask_request.form.get("input_mode", "").strip()

        try:
            if input_mode == "name":
                name = flask_request.form.get("dataset_name", "").strip()
                if not name:
                    raise ValueError(toolkit._("Please enter a dataset name or UUID."))
                return toolkit.redirect_to(
                    "/hvd-validator?{params}".format(
                        params=urlencode(
                            {
                                "input_mode": "name",
                                "dataset_name": name,
                            }
                        )
                    )
                )

            elif input_mode == "url":
                if not extra_vars["url_input_enabled"]:
                    raise ValueError(toolkit._("This input method is not enabled."))
                extra_vars["input_mode"] = input_mode
                url = flask_request.form.get("rdf_url", "").strip()
                if not url or not url.startswith(("http://", "https://")):
                    raise ValueError(toolkit._("Please enter a valid HTTP(S) URL."))
                extra_vars["input_value"] = url
                extra_vars["result"] = validate_from_url(url)

            elif input_mode == "file":
                if not extra_vars["file_input_enabled"]:
                    raise ValueError(toolkit._("This input method is not enabled."))
                extra_vars["input_mode"] = input_mode
                uploaded = flask_request.files.get("rdf_file")
                if not uploaded or not uploaded.filename:
                    raise ValueError(toolkit._("Please select a file to upload."))
                filename = uploaded.filename
                ext = (
                    "." + filename.rsplit(".", 1)[-1].lower()
                    if "." in filename
                    else ""
                )
                if ext not in ALLOWED_EXTENSIONS:
                    raise ValueError(
                        toolkit._("Unsupported file type '{ext}'. Allowed: {allowed}").format(
                            ext=ext,
                            allowed=", ".join(sorted(ALLOWED_EXTENSIONS)),
                        )
                    )
                file_data = uploaded.read()
                if len(file_data) > MAX_UPLOAD_BYTES:
                    raise ValueError(toolkit._("File exceeds the 5 MB size limit."))
                extra_vars["input_value"] = filename
                extra_vars["result"] = validate_from_file(file_data, filename)

            else:
                raise ValueError(toolkit._("Please select an input method."))

        except Exception as exc:
            log.warning("HVD validation error: %s", exc)
            extra_vars["error"] = str(exc)

    return _render_validator_page(extra_vars)


def get_blueprint():
    return blueprint
