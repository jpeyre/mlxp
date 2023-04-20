# class for reading resuls of experiments

import os
import json
import yaml

from tinydb import TinyDB
from tinydb.storages import JSONStorage
from tinydb import Query
from tinydb.table import Document

from mlxpy.data_structures.data_dict import DataDictList, DataDict, LAZYDATA
from mlxpy.parser import Parser, DefaultParser
from mlxpy.utils import _flatten_dict
from typing import Union, Optional, List
import pandas as pd
import abc
from mlxpy.logger import Directories





class Reader(object):
    """
    Constructs a database for the runs contained in a source directory 'src_dir'.    
    Once, created, it is possible to query the database using the method 'search'
    to get the results matching to a specific configuration setting. 
    The result of the query is returned either as a DataDictList object or a pandas dataframe.
    The queries are processed using a parser inheriting form the abstract class Parser. 
    By default, the parser is DefaultParser. 
    However, the user can provide a custom parser with a custom syntax 
    inheriting from the class Parser.

    .. py:attribute:: src_dir
        :type: str

        The absolute path of the source/parent directory 
        containing logs of the runs. 
        It must contain sub-directories 'src_dir/log_id', 
        where log_id is the uniquely assigned id of a run.

    .. py:attribute:: dst_dir
        :type: str

        The destination directory where 
        the database containing the runs is created.
        By default it is set to the source directory 'src_dir'.   
        The user can select a different location for the database 
        by setting the variable 'dst_dir' of the constructor to a different directory.  


    """


    def __init__(self,  src_dir: str,
                        dst_dir: Optional[str] = None, 
                        parser: Parser = DefaultParser(),
                        reload: bool = False):
        """
        Constructor

        :param src_dir: The path to the parent directory containing logs of several runs. 
        :param dst_dir: The destination directory where the database will be created.
        :param file_name: The name of the database (to be created if it does not already exist).  
        :param parser: A parser for querying the database.
        :param reload: Re-create the database even if it already exists.
   

        :type src_dir: str
        :type dst_dir: str (default None)
        :type file_name: str (default 'metadata')
        :type parser: Parser (default DefaultParser)
        :type reload: bool (default False)
    
        :raises PermissionError: if user has no writing priviledges on dst_dir  
        """



        self.parser = parser
        self.src_dir = os.path.abspath(src_dir)
        self.file_name = 'database'
        if dst_dir is None:
            dst_dir = self.src_dir
        self.dst_dir = _ensure_writable(dst_dir)

        self.db = TinyDB(os.path.join(self.dst_dir, self.file_name + ".json"),
                        storage=JSONStorage,
                        sort_keys=True,
                        indent=4,
                        separators=(",", ": "))        
        self.runs = self.db.table("runs")
        self._fields = self.db.table("fields")

        if not self.db.tables() or reload:
            self._create_base()

    def search(self, query_string:str ="", 
                    asPandas:bool =False)->DataDictList:
        
        """
        Searching a query in a database of runs. 

        :param query_string: a string defining the query constaints.
        :param asPandas: returns the result of the query as a pandas dataframe. 
        Otherwise returns a DataDictList object.

        :type query_string: str (default "")
        :type asPandas: bool (default False)
        :return: The result of a query either as a DataDictList or a pandas dataframe.
        :rtype: Union[DataDictList,pd.DataFrame]
        :raises SyntaxError: if the query string does not follow expected syntax. 
        """

        if query_string:
            Q = self.parser.parse(query_string)
            res = self.runs.search(Q)
        else:
            res = self.runs.all()
        res = [ DataDict(r,parent_dir=r["info.log_dir"]) for r in res ]
        res = DataDictList(res)
        if asPandas:
            res = res.toPandasDF(lazy=False)
        return res
    
    @property
    def fields(self)->pd.DataFrame:
        """
        Returns all fields of the database that are searchable.
        
        return: a dataframe of all fields contained in the database
        rtype: pd.DataFrame
        """
        fields_dict = {k: v for d in self._fields.all() for k, v in d.items()}
        df = pd.DataFrame(list(fields_dict.items()), columns=['Fields', 'Type'])
        df.set_index('Fields', inplace=True)
        return df

    def _create_base(self):
        self.db.drop_table("runs")
        self.db.drop_table("fields")
        all_fields = {}
        dir_nrs = [
            int(d)
            for d in os.listdir(self.src_dir)
            if os.path.isdir(os.path.join(self.src_dir, d))
            and d.isdigit()
        ]
        files_not_found = []
        for file_id in dir_nrs:
            path = os.path.join(self.src_dir, str(file_id))
            try:
                data, fields = _get_data(path, self.file_name)
                self.runs.insert(Document(data, doc_id=file_id))
                all_fields.update(fields)                    
            except FileNotFoundError:
                files_not_found.append(path)
        
        for key, value in all_fields.items():
            self._fields.insert({key: value})

        if files_not_found:
            print("Warning: The following files were not found:")
            print(files_not_found)

def _get_data( path, metadata_file):
    data = {'config':{}, 'info':{},'mlxpy':{}}
    for key in data:
        fname = os.path.join(path, Directories.Metadata.value, key + ".yaml")
        with open(fname, "r") as file:
            data[key] = yaml.safe_load(file)

    metadata_dict = _flatten_dict(data,parent_key="")
    
    fields = {key: str(type(value)) 
                    for key, value in metadata_dict.items()}
    keys_dir = os.path.join(path, Directories.Metrics.value, ".keys" )
    
    lazydata_dict = {}
    try:
        for file_name in os.listdir(keys_dir):
            if file_name.endswith('.yaml'):
                prefix = os.path.splitext(file_name)[0]
                full_file_name = os.path.join(keys_dir,file_name)
                with open(full_file_name, "r") as f:
                    keys_dict = yaml.safe_load(f)
                lazydata_dict.update({ prefix+'.'+key: LAZYDATA 
                                    for key in keys_dict.keys()})
    except FileNotFoundError:
        pass

    fields.update({key: LAZYDATA 
            for key, value in lazydata_dict.items()})

    metadata_dict.update(lazydata_dict)
    return metadata_dict, fields


def _ensure_writable(dst_dir):
    err_msg = "Please select a different destination directory."
    try:
        os.makedirs(dst_dir, exist_ok=True)
    except PermissionError:
        message = f"Unable to create the destination directory {dst_dir}.\n"
        raise PermissionError(message + err_msg)
    if not os.access(dst_dir, os.W_OK):
        message = f"Unable to access the destination directory {dst_dir}.\n"
        raise PermissionError(message + err_msg)            
    return dst_dir
