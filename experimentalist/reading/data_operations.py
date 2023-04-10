from __future__ import annotations
import os
import json
import yaml
from collections import defaultdict
from copy import deepcopy
from experimentalist.utils import _flatten_dict
from pathlib import Path
import itertools
from functools import reduce
import pandas as pd
from collections.abc import Mapping, MutableSequence, MutableMapping, KeysView, ItemsView
from experimentalist.reading.aggregation_maps import AggregationMap

from typing import List, Dict, Tuple

LAZYDATA="LAZYDATA"


class Config(Mapping):
    """
    A dictionary containing the configs and logs of a given a single run.
    Each key represents a given config or particular type of output data of the run.
    By default the keys corresponding to configs are preceeded by the prefix "metadata.", 
    while those corresponding to a user defined output are preceeded by the file name 
    containing such output (e.g. "metrics."). Example of keys:
    - "metadata.system.status"
    - "metrics.loss"

    .. note:: Except for configuration information stored in the file "metadata.yaml", 
        all outputs comming from the outputs of a run are stored in "lazy mode". 
        This means that data corresponding to a given key are not stored in the dictionary at creation to save memory. 
        The data is loaded only when user accesses a given key of the dictionary.  
    """


    def __init__(self,flattened_dict, parend_dir):
        #flattened_dict = _flatten_dict(config_dict, parent_key=parent_key) 
        self.config = { "flattened": flattened_dict,
                        "lazy": LazyDict(flattened_dict)}
        #parent_dir = self.config["flattened"][self.parent_key+"logs.path"]
        self.parend_dir = parend_dir
        self._make_lazydict()

    def __getitem__(self,key):
        return self.config['lazy'][key]
    def __iter__(self):
        return iter(self.config['lazy'])

    def __len__(self):
        return len(self.config['lazy'])
    def __repr__(self):
        return repr(self.config['flattened'])

    def _repr_html_(self):
        import pandas as pd
        df = pd.DataFrame([self.config['flattened']])
        return df._repr_html_() 
    def keys(self):

        return self.config['lazy'].keys()

    def items(self):

        return self.config['lazy'].items()

    def flattened(self):
        return self.config['flattened']
    def lazy(self):
        return self.config['lazy']
    def _make_lazydict(self):
        all_keys = [ key for key,value in self.config["flattened"].items() 
                            if value==LAZYDATA ]
        parent_keys = set([key.split('.')[0] for  key in all_keys]) 
        try:
            self.lazydata_dict = {parent_key: LazyData(self.parent_dir,parent_key) 
                                    for parent_key in parent_keys }
        except:
            pass
        
        self.config['lazy'].update({ key: self.lazydata_dict[key.split('.')[0]].get_data 
                                    for key in all_keys})

    def update(self, new_dict):
        copy_dict = {key: LAZYDATA if callable(value) 
                        else value 
                        for key,value in new_dict.items()  }
        self.config["lazy"].update(new_dict)
        self.config["flattened"].update(copy_dict)        
        

    def free_unused(self):
        for key, data in self.lazydata_dict.items():
            data.free_unused()


class LazyDict(MutableMapping):
    def __init__(self, *args, **kw):
        self._raw_dict = dict(*args, **kw)

    def __getitem__(self, key):
        obj = self._raw_dict.__getitem__(key)
        if callable(obj):
            return obj(key)
        else:
            return obj

    def __iter__(self):
        return iter(self._raw_dict)

    def __len__(self):
        return len(self._raw_dict)

    def __delitem__(self,key):
        del self._raw_dict[key]
    def __setitem__(self,key,value):
        self._raw_dict[key]=value


class LazyData(object):
    def __init__(self,parent_dir, file_name):
        self.file_name = file_name
        self.parent_dir = parent_dir
        self.path = os.path.join(self.parent_dir, self.file_name + ".json")
        dir_name =os.path.join('src_dir',os.path.basename(self.parent_dir),self.file_name)
        self.display_message = f"Lazy loading from: {dir_name}"
        self.used_keys = set()
        self._data = None
    def get_data(self, key):
        if self._data is None or key not in self.used_keys:
            self._data = _load_dict_from_json(self.path, self.file_name)
            self.used_keys.add(key)
        return self._data[key]
    def free_unused(self):
        all_keys = set(self._data.keys())
        unused_keys = all_keys.difference(self.used_keys)
        for key in unused_keys:
            del self._data[key]


class ConfigList(list):
    """
    A list of elements of type Config. This list can be viewed as a dataframe 
    where each row represents a given run and columns represent 
    the configurations and results for each run.  
    
    It is displayed as a pandas dataframe and 
    can be converted to it using toPandasDF method.


    """    


    def __init__(self, iterable: List[Config]):
        if iterable:
            for config in iterable:
                assert isinstance(config, Config) 
        super().__init__(item for item in iterable)
        self.pandas=None
        self._keys=None

    def __repr__(self):
        return str(self.toPandasDF())

    def _repr_html_(self):
        return self.toPandasDF()._repr_html_()  

    def toPandasDF(self)->pd.DataFrame:
        """
        Converts the list into a pandas dataframe.

        :return: A panda dataframe containing logs (configs and data) 
        of the ConfigList object
        :rtype: pd.DataFrame

        """
        
        if self.pandas is None:
            self.pandas = pd.DataFrame([config.flattened() for config in self])
        return self.pandas
    
    def keys(self)->List[str]:
        """
        Returns a list of column names of the dataframe. 

        :return: List of strings containing the column names of the dataframe
        :rtype: List[str]
        """
        if self._keys is None:
            self._keys = list(self.toPandasDF().keys())
        return self._keys

    def groupBy(self, list_group_keys:List[str] )->GroupedConfigs:

        """
            Performs a groupby operation on the dataframe 
            according to a list of colum names (list_group_keys). 
            Returns an object of the class GroupedConfigs 

            :params list_group_keys: a list of strings containing the names of the columns to be grouped.
            :type list_group_keys: List[str]
            :return: A hierarchical dataframe grouped by the values of the columns provided to list_group_keys.
            :rtype: GroupedConfigs
            :raises InvalidKeyError: if one of the provided keys does not match any columns of the dataframe.

        """
        # Check if keys are valid
        for key in list_group_keys:
            _check_valid_key(self.keys, key)

        # Need to handle the case when keys are empty
        collection_dict, group_keys, group_vals = _group_by(self, list_group_keys)
        # pandas_grouped_df = deepcopy(self.toPandasDF()).set_index(list_group_keys)
        grouped_config = GroupedConfigs(collection_dict, group_keys, group_vals)
        #grouped_config.pandas = pandas_grouped_df
        return grouped_config

    def config_diff(self, start_key="metadata.custom")->List[str]:
        """
            Returns a list of colums keys starting with 'start_key' 
            and whose value varies in the dataframe.
            
            :param start_key: A string with which all column names to be considered must start. 
            :type start_key: str (default 'metadata.custom')
            :return: A list of strings containing the column names 
            starting with 'start_key' and whose values vary in the dataframe.
            :rtype: List[str]
        """
        


        diff_keys = []
        ref_dict = None
        
        for config in self:
            #config_dict = config.hierarchical()["custom"]
            #config_dict = _flatten_dict(config_dict, parent_key="metadata.custom")
            if ref_dict is None:
                ref_dict = config
            else:
                for key in config.keys():
                    if key in ref_dict and key.startswith(start_key):
                        if ref_dict[key] != config[key]:
                            if key not in diff_keys:
                                diff_keys.append(key)
                    else:
                        if key not in diff_keys:
                            diff_keys.append(key)
        return diff_keys

class GroupedConfigs:
    """
    A dictionary where each key represents the tuple of values taken by the grouped column of some processed dataframe. 
    The values corresponsing to each key are objects of type ConfigList containing a group. 
    This object is usually obtained as the output of the group_by method of the class  ConfigList.
    It is displayed as a hierarchical pandas dataframe and 
    can be converted to it using toPandasDF method.

    .. py:attribute:: group_keys
        :type: List[str]

        A list of string containing the column names used for grouping.
    
    .. note:: It is possible to directly access the keys and values of self.grouped_dict 
            by identifying self with self.grouped_dict:
            
            - Using self[key] instead of self.grouped_dict[key] to access the value of self.grouped_dict at a given key  
            
            - Using self.keys() to get all keys of self.grouped_dict.
            
            - Using self.items() to iterate over the key/value pairs of self.grouped_dict.
    """  


    def __init__(self, group_keys:List[str], 
                        grouped_dict:Dict[Tuple[str, ...], ConfigList]):   
        """
        Constructor
        :param group_keys: A list of string containing the column names used for grouping.
        :param grouped_dict: A dictionary where each key represents the tuple of values 
        taken by the grouped column of some processed dataframe. 
        The values corresponsing to each key are objects of type ConfigList containing a group. 

        :type group_keys: List[str]
        :type grouped_dict: Dict[Tuple[str, ...], ConfigList]

        """

        self.group_keys = group_keys
        self.grouped_dict = grouped_dict
        self.group_vals = list(self.grouped_dict.keys())
        self._current_index = 0
        self.groups_size = len(self.group_vals)
        self.pandas = None
    def __iter__(self):
            return iter(self.grouped_dict)
    # def __next__(self):
    #     if self._current_index < self.groups_size:
    #         keys = self.group_vals[self._current_index]
    #         # key_dict = dict(zip(self.group_keys, keys))
    #         dict_val = self.__getitem__(keys)
    #         self._current_index += 1
    #         return keys, dict_val
    #     self._current_index = 0
    #     raise StopIteration

    def __getitem__(self, key:Tuple[str, ...])->ConfigList:
        """
        Returns the value of the dictionary at a given key key
        """

        return self.grouped_dict[keys]

    def __repr__(self):

        return str(self.toPandasDF())
    
    def items(self)->ItemsView:
        """
        Return the items of the grouped dictionary
            
        :return: items of the dictionary
        :rtype: ItemsView
        """

        return self.grouped_dict.items()
    
    def keys(self)->KeysView:
        """
        Return the keys of the grouped dictionary
        
        :return: keys of the dictionary    
        :rtype: KeysView
        """


        return self.grouped_dict.keys()


    def toPandasDF(self)->pd.DataFrame:
        """
        Converts the list into a pandas dataframe.

        :return: A panda dataframe containing logs (configs and data) 
        of the ConfigList object
        :rtype: pd.DataFrame

        """
        if self.pandas is None:
            all_configs = []
            for key, value in self.grouped_dict.items():
                all_configs+=[el for el in value ]
            self.pandas = ConfigList(all_configs).toPandasDF().set_index(list(self.group_keys))
        return self.pandas

    def aggregate(self, aggregation_maps: List[AggregationMap])->Dict[str,GroupedConfigs]:
        """
        Performs aggregation of the leaf dataframes according to some aggregation maps provided as input. 
        It returns a dictionary of key value pairs, where each key represents an aggregation map 
        and its value is an aggregated result returned as a GroupedConfigs objects 
        preserving the same hierarchy as the current object.
        
        :params aggregation_maps: A list of aggregation maps. 
            Each map must be an instance of class inheriting from the abstract class AggregationMap. 
        :type aggregation_maps: List[AggregationMap]
        :return: A dictionary of aggregated results indexed by the aggregation maps. 
        :rtype: Dict[str,GroupedConfigs]
        :raises InvalidAggregationMapError: if one of the aggregation map is not an instance of a class 
        inheriting from the abstract class AggregationMap.
        """
        for agg_map in aggregation_maps:
            _assert_valid_map(agg_map)

        return _aggregate(self, aggregation_maps)

class InvalidKeyError(Exception):
    """
    Raised when the key is invalid
    """
    pass

class InvalidAggregationMapError(Exception):
    """
    Raised when an aggregation map is not an instance of AggregationMap.
    """
    pass



def _group_by(config_dicts, list_group_keys):

    collection_dict = {}
    group_vals = set()
    group_keys = tuple(list_group_keys)
    for config_dict in config_dicts:

        pkey_list = [ config_dict.flattened()[group_key] 
            for group_key in list_group_keys
        ]
        pkey_val = [str(pkey) for pkey in pkey_list if pkey is not None]
        group_vals.add(tuple(pkey_val))
        _add_nested_keys_val(
            collection_dict,  pkey_val, [config_dict]
        )
    group_vals = list(group_vals)
    
    grouped_dict = { key: ConfigList(reduce(dict.get, key, collection_dict)) 
                                for key in group_vals }

    return grouped_dict, group_keys, group_vals
    




def _add_nested_keys_val(dictionary,keys,val):
    dico = dictionary
    parent = None
    for key in keys:
        parent = dico
        try:
            dico = dico[key]
        except KeyError:
            dico[key] = {}
            dico = dico[key]
    try:
        parent[key] = dico + val
    except TypeError as e:
        #print(e)
        parent[key] = val
     

def _aggregate(groupedconfigs, aggregation_maps):
    # Returns a hierarchical dictionary whose leafs are instances of ConfigList

    #agg_dict = AggregatedConfigs({})
    agg_config_dict = {agg_map.name: {} for agg_map in  aggregation_maps}
    for keys, config_list in groupedconfigs.items():
        
        agg_config = _aggregate_collection(config_list, aggregation_maps)
        #keys = list(keys_vals.values())
        for agg_map in aggregation_maps:
            _add_nested_keys_val(agg_config_dict[agg_map.name], keys, agg_config[agg_map.name])

            
    return {agg_map.name : GroupedConfigs(agg_config_dict[agg_map.name], 
                                        groupedconfigs.group_keys, 
                                        groupedconfigs.group_vals) for agg_map in aggregation_maps}


def _aggregate_collection(collection, agg_maps):
    value_keys = _extract_keys_from_maps(agg_maps)
    agg_collection = {}

    val_array = []
    for config_dict in collection:
        data = {key: config_dict[key] for key in value_keys}
        val_array.append(data)
        config_dict.free_unused()

    for agg_map in agg_maps:
        agg_val, index = agg_map.apply(val_array)
        if index is not None:
            new_collection= ConfigList([deepcopy(collection[index])])
        else:
            new_collection = deepcopy(collection)
        for config_dict in new_collection:
            config_dict.update(agg_val)
        agg_collection[agg_map.name] = new_collection

    return agg_collection


def _load_dict_from_json(json_file_name, file_name):
    out_dict = {}
    try:
        with open(json_file_name) as f:
            for line in f:
                cur_dict = json.loads(line)
                keys = cur_dict.keys()
                for key in keys:
                    full_key = file_name + "." + key
                    if full_key in out_dict:
                        out_dict[full_key].append(cur_dict[key])
                    else:
                        out_dict[full_key] = [cur_dict[key]]
    except Exception as e:
        print(str(e))
    return out_dict

def _extract_keys_from_maps(agg_maps):
    seen = set()
    extracted_keys = []
    for agg_map in agg_maps:
        extracted_keys += [
            key for key in agg_map.keys if key not in seen and not seen.add(key)
        ]

    return extracted_keys



def _check_valid_key(valid_keys,key):
    try:
        assert key in valid_keys
    except AssertionError:
        message = f"The provided key {key} is invalid! Valid keys are: {str(valid_keys)}"
        raise InvalidKeyError(message)

def _assert_valid_map(agg_map):
    try:
        assert issubclass(type(agg_map), AggregationMap)
    except AssertionError:
        message = f"The map {str(agg_map)} must be an instance of a child class of  {str(AggregationMap)}"
        raise InvalidAggregationMapError(message)

