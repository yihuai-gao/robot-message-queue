from robotmq import safe_serialize, safe_deserialize
import numpy as np

data = np.array([1, 2, 3, 4, 5])

serialized_data = safe_serialize(data)
recovered_data = safe_deserialize(serialized_data)
print(f"recovered_data: {recovered_data}")

data_dict = {"data": data}
data_dict_serialized = safe_serialize(data_dict)
recovered_data_dict = safe_deserialize(data_dict_serialized)
print(f"recovered_data_dict: {recovered_data_dict}")

data_dict_dict = {"data_dict": data_dict}
data_dict_dict_serialized = safe_serialize(data_dict_dict)
recovered_data_dict_dict = safe_deserialize(data_dict_dict_serialized)
print(f"recovered_data_dict_dict: {recovered_data_dict_dict}")

data_list = [data, data_dict, data_dict_dict]
data_list_serialized = safe_serialize(data_list)
recovered_data_list = safe_deserialize(data_list_serialized)
print(f"recovered_data_list: {recovered_data_list}")

data_tuple = (data, data_dict, data_dict_dict)
data_tuple_serialized = safe_serialize(data_tuple)
recovered_data_tuple = safe_deserialize(data_tuple_serialized)
print(f"recovered_data_tuple: {recovered_data_tuple}")

