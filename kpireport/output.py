from abc import ABC, abstractmethod

from kpireport.plugin import PluginManager


class OutputDriverError(Exception):
    pass


class OutputDriver(ABC):
    """
    Attributes:
        report (:class:`~kpireport.report.Report`): the current report.
        id (str): the Output driver ID declared in the report configuration.
        supported_formats (List[str]): a list of output formats supported by this
            driver. Defaults to ``["md", "html"]``.
    """

    id: str = None
    supported_formats: "List[str]" = ["md", "html"]

    def __init__(self, report: "kpireport.report.Report", **kwargs):
        self.report = report
        if "id" in kwargs:
            self.id = kwargs.pop("id")
        self.init(**kwargs)

    @abstractmethod
    def init(self, **kwargs):
        """Initialize the output driver from the report configuration.

        Args:
            **kwargs: Arbitrary keyword arguments, declared as ``args``
                in the report configuration.
        """
        pass

    def render_blob_inline(self, blob, fmt=None):
        raise NotImplementedError(f"'{self.id}' driver does not support inline blobs")

    def can_render(self, fmt: str) -> bool:
        """Determine if this driver supports a given output format.

        Args:
            fmt (str): the desired output format.

        Returns:
            bool: whether the output format can be rendered.
        """
        return fmt in self.supported_formats

    @abstractmethod
    def render_output(self, content: "kpireport.report.Content", blobs):
        """Render the report content for the target delivery mechanism.

        Args:
            content (:class:`~kpireport.report.Content`): the report contents.
            blobs (List[Blob]): the blobs generated as part of the report.
        """
        pass


class OutputDriverManager(PluginManager):
    namespace = "kpireport.output"
    type_noun = "output driver"
    exc_class = OutputDriverError
