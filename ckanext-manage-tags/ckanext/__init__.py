from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)

try:
    import pkg_resources

    pkg_resources.declare_namespace(__name__)
except ImportError:
    pass
