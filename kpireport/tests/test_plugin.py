import unittest
from unittest.mock import MagicMock

from kpireport.plugin import PluginManager
from kpireport.tests.utils import BaseTestPlugin, make_test_extension_manager

NAME = "my_name"
PLUGIN = "my_plugin"


class TestException(Exception):
    pass


class TestPluginManager(PluginManager):
    exc_class = TestException


class PluginManagerTestCase(unittest.TestCase):
    def _make_plugin_manager(
        self, conf={NAME: {"plugin": PLUGIN}}, plugins=[(PLUGIN, MagicMock())]
    ):
        mgr = make_test_extension_manager(plugins)
        return TestPluginManager(MagicMock(), conf, extension_manager=mgr)

    def test_missing_plugin(self):
        mgr = self._make_plugin_manager(conf={NAME: {}})
        self.assertIsInstance(mgr.errors(NAME)[0], TestException)

    def test_invalid_plugin(self):
        mgr = self._make_plugin_manager(conf={NAME: {"plugin": "missing"}})
        self.assertIsInstance(mgr.errors(NAME)[0], TestException)

    def test_invalid_args(self):
        mgr = self._make_plugin_manager(conf={NAME: {"plugin": PLUGIN, "args": "foo"}})
        self.assertIsInstance(mgr.errors(NAME)[0], TestException)

    def test_error_on_invoke(self):
        def test_plugin():
            raise ValueError("I'm a bad plugin!")

        mgr = self._make_plugin_manager(plugins=[(PLUGIN, test_plugin)])
        self.assertIsInstance(mgr.errors(NAME)[0], TestException)

    def test_call_instance(self):
        class TestPlugin(BaseTestPlugin):
            def my_method(self, posarg, kwarg=None):
                return (posarg, kwarg)

        mgr = self._make_plugin_manager(plugins=[(PLUGIN, TestPlugin)])
        self.assertEqual(mgr.call_instance(NAME, "my_method", 1, kwarg=2), (1, 2))

    def test_multiple_instances(self):
        class TestPlugin(BaseTestPlugin):
            def my_method(self, posarg):
                return posarg

        mgr = self._make_plugin_manager(
            conf={
                "first": {"plugin": PLUGIN},
                "second": {"plugin": PLUGIN},
            },
            plugins=[(PLUGIN, TestPlugin)],
        )

        self.assertEqual(mgr.call_instance("second", "my_method", "arg"), "arg")

    def test_multiple_plugins(self):
        class FirstTestPlugin(BaseTestPlugin):
            def my_method(self, input):
                return None

        class SecondTestPlugin(BaseTestPlugin):
            def my_method(self, input):
                return input

        mgr = self._make_plugin_manager(
            plugins=[("first", FirstTestPlugin), (PLUGIN, SecondTestPlugin)]
        )

        self.assertEqual(mgr.call_instance(NAME, "my_method", "arg"), "arg")
