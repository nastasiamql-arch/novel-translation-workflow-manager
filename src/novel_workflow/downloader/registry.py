from .sources import TomatoMTLSource, load_configurable_sources


class SourceRegistry:
    def __init__(self, sources=()):
        self._sources = {}
        self.load_errors = ()
        for source in sources:
            self.register(source)

    def register(self, source):
        if not source.id:
            raise ValueError("Source must have an id")
        if source.id in self._sources:
            raise ValueError(f"Source id is already registered: {source.id}")
        self._sources[source.id] = source

    def get(self, source_id):
        try:
            return self._sources[source_id]
        except KeyError as exc:
            raise ValueError(f"Unknown source: {source_id}") from exc

    def match(self, url):
        matches = [source for source in self._sources.values() if source.can_handle(url)]
        if len(matches) != 1:
            raise ValueError("No supported source recognizes this URL" if not matches else "More than one source recognizes this URL")
        return matches[0]

    def list_sources(self):
        return tuple(self._sources.values())

    @classmethod
    def builtins(cls, custom_dir=None):
        sources = [TomatoMTLSource()]
        errors = []
        if custom_dir:
            sources.extend(load_configurable_sources(custom_dir, errors=errors))
        registry = cls(sources[:1])
        for source in sources[1:]:
            try:
                registry.register(source)
            except ValueError as exc:
                errors.append(f"{source.id}: {exc}")
        registry.load_errors = tuple(errors)
        return registry


def default_registry(custom_dir=None):
    return SourceRegistry.builtins(custom_dir)
