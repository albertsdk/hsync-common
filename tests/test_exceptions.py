"""Tests for hsync_common.exceptions."""

import pytest

from hsync_common.exceptions import HSyncError


class TestHSyncErrorDefaults:
    def test_default_message(self):
        err = HSyncError()
        assert err.message == HSyncError.default_message

    def test_default_error_code(self):
        err = HSyncError()
        assert err.error_code == "HSYNC-5000"

    def test_default_details_empty(self):
        err = HSyncError()
        assert err.details == {}

    def test_str_is_message(self):
        err = HSyncError("something went wrong")
        assert str(err) == "something went wrong"


class TestHSyncErrorCustomValues:
    def test_custom_message(self):
        err = HSyncError("custom message")
        assert err.message == "custom message"

    def test_custom_details(self):
        details = {"file": "foo.txt", "code": 42}
        err = HSyncError(details=details)
        assert err.details == details

    def test_message_and_details(self):
        err = HSyncError("oops", details={"x": 1})
        assert err.message == "oops"
        assert err.details == {"x": 1}

    def test_none_message_falls_back_to_default(self):
        err = HSyncError(None)
        assert err.message == HSyncError.default_message


class TestHSyncErrorToDict:
    def test_to_dict_contains_error_and_message(self):
        err = HSyncError("test")
        d = err.to_dict()
        assert "error" in d
        assert "message" in d
        assert d["message"] == "test"
        assert d["error"] == "HSYNC-5000"

    def test_to_dict_no_details_key_when_empty(self):
        err = HSyncError("test")
        d = err.to_dict()
        assert "details" not in d

    def test_to_dict_includes_details_when_present(self):
        err = HSyncError("test", details={"key": "value"})
        d = err.to_dict()
        assert "details" in d
        assert d["details"] == {"key": "value"}


class TestHSyncErrorSubclassing:
    def test_subclass_can_override_code_and_message(self):
        class MyError(HSyncError):
            error_code = "MY-1001"
            default_message = "my default"

        err = MyError()
        assert err.error_code == "MY-1001"
        assert err.message == "my default"

    def test_subclass_to_dict_uses_overridden_code(self):
        class MyError(HSyncError):
            error_code = "MY-1002"

        d = MyError("test").to_dict()
        assert d["error"] == "MY-1002"

    def test_subclass_is_catchable_as_hsync_error(self):
        class MyError(HSyncError):
            pass

        with pytest.raises(HSyncError):
            raise MyError("subclass error")
