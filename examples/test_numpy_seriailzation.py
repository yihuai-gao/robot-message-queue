from robotmq import serialize_numpy, deserialize_numpy
import numpy as np

data = np.array([1, 2, 3, 4, 5])

serialized_data = serialize_numpy(data)
recovered_data = deserialize_numpy(serialized_data)
print(f"recovered_data: {recovered_data}")

data_dict = {"data": data}
data_dict_serialized = serialize_numpy(data_dict)
recovered_data_dict = deserialize_numpy(data_dict_serialized)
print(f"recovered_data_dict: {recovered_data_dict}")

data_dict_dict = {"data_dict": data_dict}
data_dict_dict_serialized = serialize_numpy(data_dict_dict)
recovered_data_dict_dict = deserialize_numpy(data_dict_dict_serialized)
print(f"recovered_data_dict_dict: {recovered_data_dict_dict}")

data_list = [data, data_dict, data_dict_dict]
data_list_serialized = serialize_numpy(data_list)
recovered_data_list = deserialize_numpy(data_list_serialized)
print(f"recovered_data_list: {recovered_data_list}")

data_tuple = (data, data_dict, data_dict_dict)
data_tuple_serialized = serialize_numpy(data_tuple)
recovered_data_tuple = deserialize_numpy(data_tuple_serialized)
print(f"recovered_data_tuple: {recovered_data_tuple}")

