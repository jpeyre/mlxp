import os
import numpy as np



class AggregationMap:
    """
    An abstract class whose children can perform aggregations on arrays. 
    
    """


    def __init__(self, keys, func=None, args={}, map_name=""):
        self.func = func
        self.keys = keys
        self.args = args
        self.map_name = map_name
        self.name = self.make_name()
    def make_name(self):
        return self.map_name + "(" + ",".join(self.keys) + ")"
    
    def apply(self, data):
        # Input: List of dicts where each entry of the list
        # contains data corresponding to a config.
        # Output: Dict of outputs
        raise NotImplementedError
    


class Last(AggregationMap):
    def __init__(self, key):
        super().__init__([key], map_name="last")
    def apply(self, data):
        key = self.keys[0]
        try:
            return {self.name: data[key][-1]}
        except KeyError:
            return {}
        except IndexError:
            return {}


class Min(AggregationMap):
    def __init__(self, key):
        super().__init__([key], map_name="min")

    def apply(self, data):
        index = -1
        selected_data = [d[self.keys[0]] for d in data]
        try:
            index = np.nanargmin(np.asarray(selected_data), axis=0)
        except ValueError:
            pass
        return {self.name: selected_data[index]}, index


class Max(AggregationMap):
    def __init__(self, key):
        super().__init__([key], map_name="max")

    def apply(self, data):
        index = -1
        selected_data = [d[self.keys[0]] for d in data]
        try:
            index = np.nanargmax(np.asarray(selected_data), axis=0)
        except ValueError:
            pass
        return {self.name: selected_data[index]}, index


class AvgStd(AggregationMap):
    def __init__(self, key):
        super().__init__([key], map_name="avgstd")
    def apply(self, data):

        data = [{key: d[key] for key in self.keys} for d in data]
        out, _ = _compute_mean_and_std(data)
        return out, None


def _compute_mean_and_std(data_list, log_scale=False):
    index = None  # mean and std does not result an index unlike min and max.
    if len(data_list) == 1:
        out = {key + "_avg": value for key, value in data_list[0].items()}
        out.update(
            {key + "_std": np.zeros(len(value)) for key, value in data_list[0].items()}
        )
        return out, index
    keys = list(data_list[0].keys())
    out = {}
    for i, p in enumerate(data_list):
        for key in keys:
            if i == 0:
                len_data = len(p[key])
                out[key + "_avg"] = np.zeros(len_data)
                out[key + "_std"] = np.zeros(len_data)
            else:
                len_data = min(out[key + "_avg"].size, len(p[key]))

            new_array = np.asarray(p[key])[:len_data]
            if log_scale:
                new_array = np.log(new_array)
            out[key + "_avg"] = out[key + "_avg"][:len_data] + new_array
            out[key + "_std"] = out[key + "_std"][:len_data] + new_array ** 2

    for key in keys:
        out[key + "_avg"] = out[key + "_avg"] / (i + 1)
        out[key + "_std"] = out[key + "_std"] / (i + 1) - (out[key + "_avg"]) ** 2
        out[key + "_std"] = np.sqrt(out[key + "_std"])

    return out, index