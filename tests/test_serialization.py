"""Tests for robotmq serialize/deserialize utilities."""

import numpy as np
import pytest
from robotmq import serialize, deserialize


class TestSerializeDeserialize:
    def test_numpy_array_1d(self):
        arr = np.array([1.0, 2.0, 3.0])
        result = deserialize(serialize(arr))
        np.testing.assert_array_equal(result, arr)

    def test_numpy_array_multidimensional(self):
        arr = np.random.rand(4, 5, 3)
        result = deserialize(serialize(arr))
        np.testing.assert_array_equal(result, arr)

    def test_numpy_array_dtypes(self):
        for dtype in [np.float32, np.float64, np.int32, np.int64, np.uint8, np.bool_]:
            arr = np.array([1, 2, 3], dtype=dtype)
            result = deserialize(serialize(arr))
            np.testing.assert_array_equal(result, arr)
            assert result.dtype == arr.dtype

    def test_dict_with_numpy(self):
        data = {"image": np.random.rand(3, 4), "label": 42}
        result = deserialize(serialize(data))
        np.testing.assert_array_equal(result["image"], data["image"])
        assert result["label"] == 42

    def test_nested_dict(self):
        data = {
            "outer": {
                "inner": np.array([1, 2, 3]),
                "value": "hello",
            },
            "number": 3.14,
        }
        result = deserialize(serialize(data))
        np.testing.assert_array_equal(result["outer"]["inner"], data["outer"]["inner"])
        assert result["outer"]["value"] == "hello"
        assert result["number"] == 3.14

    def test_list_of_arrays(self):
        data = [np.array([1, 2]), np.array([3, 4, 5])]
        result = deserialize(serialize(data))
        assert len(result) == 2
        np.testing.assert_array_equal(result[0], data[0])
        np.testing.assert_array_equal(result[1], data[1])

    def test_tuple_of_arrays(self):
        data = (np.array([1, 2]), np.array([3, 4]))
        result = deserialize(serialize(data))
        assert isinstance(result, tuple)
        np.testing.assert_array_equal(result[0], data[0])
        np.testing.assert_array_equal(result[1], data[1])

    def test_plain_types(self):
        for data in [42, 3.14, "hello", True, None, b"raw bytes"]:
            result = deserialize(serialize(data))
            assert result == data

    def test_empty_list(self):
        result = deserialize(serialize([]))
        assert result == []

    def test_empty_dict(self):
        result = deserialize(serialize({}))
        assert result == {}

    def test_empty_bytes_returns_none(self):
        with pytest.warns(UserWarning, match="empty data"):
            result = deserialize(b"")
        assert result is None

    def test_deeply_nested(self):
        arr = np.array([1.0, 2.0])
        data = {"a": [{"b": (arr, {"c": arr})}]}
        result = deserialize(serialize(data))
        np.testing.assert_array_equal(result["a"][0]["b"][0], arr)
        np.testing.assert_array_equal(result["a"][0]["b"][1]["c"], arr)

    def test_deserialized_array_is_writable(self):
        arr = np.array([1.0, 2.0, 3.0])
        result = deserialize(serialize(arr))
        result[0] = 99.0  # should not raise
        assert result[0] == 99.0
