"""Test cases for the base Property class"""

from velbusaio.channels import Channel
from velbusaio.properties import Property


class TestProperty:
    """Test cases for the base Property class."""

    def test_name_is_never_editable(self, mock_module, mock_writer):
        """A property name comes from the library, not from the module."""
        prop = Property(mock_module, "PSU Power", mock_writer)
        assert not prop.is_name_editable()

    def test_channels_and_properties_answer_the_same_question(
        self, mock_module, mock_writer
    ):
        """Both item types expose is_name_editable(), so callers need no isinstance.

        A consumer walking a module's channels and properties together has to be
        able to ask any item whether its name is user-editable; that is the whole
        reason the method exists on both.
        """
        items = [
            Channel(mock_module, 1, "Test", True, True, mock_writer, 0x01),
            Property(mock_module, "PSU Power", mock_writer),
        ]
        assert [item.is_name_editable() for item in items] == [True, False]
