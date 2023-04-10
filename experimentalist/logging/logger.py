# class for logging experiments


import sys
import os
import socket
import json
import yaml
import omegaconf
import importlib
from datetime import datetime
import random
from time import sleep
import dill as pkl
import shutil
from dataclasses import dataclass
from typing import Any, Type, Dict, Union
import abc
from enum import Enum
from experimentalist.logging.artifacts import Artifact




class Status(Enum):
    """
        Status of a run. 

        The status can take the following values:

        - STARTING: The metadata for the run have been created.

        - RUNNING: The experiment is currently running. 
        
        - COMPLETE: The run is  complete and did not through any error.
        
        - FAILED: The run stoped due to an error.
    """


    STARTING = "STARTING"
    COMPLETE = "COMPLETE"
    RUNNING = "RUNNING"
    FAILED = "FAILED"

class ConfigDict(dict):
    def __init__(self, *args, **kwargs):
        super(ConfigDict, self).__init__(*args, **kwargs)
        self.__dict__ = self


class Logger:
    """ 
    The class defines a logger which provides all metatdata for the run 
    and allows saving outputs of the run in a uniquely assigned directory for 
    the specific run.

    .. py:attribute:: config
        :type: omegaconf.dictconfig.DictConfig 

        An object containing the configuration metadata for the run.

    """
    def __init__(self, config):
        """
        Constructor

        :param config: An object containing the configuration metadata for the run.
        :type config: omegaconf.dictconfig.DictConfig

        """


        self.config = config

        parent_log_dir = self.config.logs.parent_log_dir
        self._root = os.path.join(parent_log_dir, self.config.logs.log_name)
        self._run_id, self._run_dir = _make_run_dir(config.logs.log_id, 
                                                    self._root)
        
        self._update_config()
        self._metric_dict_keys = []
        if self.config.logs.log_to_file:
            log_file = open(os.path.join(self._run_dir, "log.txt"), "w", buffering=1)
            sys.stdout = log_file
            sys.stderr = log_file

    @property
    def config_dict(self)->Dict[str, Any] :
        """A dictionary of the configuration metadata for the run. 
        
        .. note:: The returned dictionary is mutable, unlike the config property which is immutable
        
        :rtype: Dict[str, Any]
        :return: The metadata for the run in mutable form
        """
        return DictConfig_to_dict(self.config)


    @property
    def root(self):
        """Returns the root directory. Ensures the root to be immutable.
        
        :rtype: str
        :return: The root directory of the run.
        """
        return self._root

    @property
    def run_id(self):
        """Returns the uniquely assigned id of the run. Ensures the run_id to be immutable.
        
        :rtype: int
        :return: The id of the run.
        """
        return self._run_id

    @property
    def run_dir(self):
        """Returns the path to the directory where outputs of the run are saved. 
        Ensures the run_dir to be immutable.
        
        :rtype: str
        :return: The path to the output directory of the run.
        """
        return self._run_dir


    def log_config(self, file_name: str ="metadata")->None:
        """
        Saves the config attribute corresponding to the current run  
        into a yaml file run_dir/file_name+'.yaml'. 

        :param file_name: Name of the target file.
        :type file_name: str (default "metadata")
        :return: None
        """

        abs_name = os.path.join(self._run_dir, file_name)
        omegaconf.OmegaConf.save(config=self.config, f=abs_name + ".yaml")


    def log_metric(self, metric_dict: Dict[str, Union[int, float, str]], 
                        file_name: str ="metrics")->None:
        """Saves a dictionary of scalars to a json file named 
        file_name+'.json' in the directory run_dir. If the file exists already, 
        the dictionary is appended at the end of the file. 

        :param metric_dict:  Dictonary of scalars values to be saved, the values can be either int, float of string.
        :param file_name: Name of the target file.
        :type artifact: Artifact
        :type file_name: str (default "metrics")
        :return: None
        """
        self._log_metrics_key(metric_dict,file_name=file_name)
        file_name = os.path.join(self._run_dir, file_name)
        with open(file_name + ".json", "a") as f:
            json.dump(metric_dict, f)
            f.write(os.linesep)

    def log_artifact(self, artifact: Artifact, file_name: str)-> None:
        """Saves the attribute obj of an instance inheriting from the abstract class Artifact 
        into a destination file: 'run_dir/artifact_class_name/file_name'. 
        The directory 'artifact_class_name' is named after 
        the child class inheriting from Artifact.   

        :param artifact:  An instance of a class inheriting from the abstract class Artifact.
        :param file_name: Name of the file where the artifact is saved.
        :type artifact: Artifact
        :type file_name: str
        :return: None
        :raises Assertionerror: if artifact is not an instance of Artifact.
        """

        assert isinstance(artifact,Artifact)
        subdir = os.path.join(self._run_dir, type(artifact).__name__)
        os.makedirs(subdir, exist_ok=True)
        fname = os.path.join(subdir, file_name)
        artifact.save(fname)

    def copy_artifact(self, src_name:str, dst_name: str, 
                            artifact_class: Artifact) -> None:
        """Copies an already existing artifact obj 
        from a source file: run_dir/artifact_class_name/src_name 
        to a destination file run_dir/artifact_class_name/dst_name, 
        where artifact_class_name is the name of the class artifact_class.  
        
        .. note:: The source file name needs to have the same extension as the attribute ext of the class artifact_class.

        :param src_name: Name of the source file to be copied.
        :param dst_name: Name of the destination file of the copy.
        :param artifact_class: A class inheriting from the abstract class Artifact.
        :type src_name: str
        :type dst_name: str
        :type artifact_class: Artifact
        :return: None
        :raises FileNotFoundError: if the source file is not found.
        """

        assert issubclass(artifact_class, Artifact)
        ckpt_dir_name = artifact_class.__name__
        ext = getattr(artifact_class, 'ext')
        subdir = os.path.join(self._run_dir, ckpt_dir_name)
        fname = os.path.join(subdir, src_name)
        copy_fname = os.path.join(subdir, dst_name)
        try:
            shutil.copy(f"{fname}{ext}", f"{copy_fname}{ext}")
        except FileNotFoundError as e:
            raise FileNotFoundError

    def _log_status(self, status: Status)->None:
        """
        Saves the status of the run into the 'metadata.yaml' file
        This function is only used internally

        :param status: Status of the run.
        :type status: Status
        :return: None
        :raises TypeError: if the status is not an instance of the class Status
        """
        if status in [Status.COMPLETE, Status.RUNNING, Status.FAILED]:
            omegaconf.OmegaConf.set_struct(self.config, True)
            with omegaconf.open_dict(self.config):
                self.config.system.status = status.name
            omegaconf.OmegaConf.set_struct(self.config, False)
            self.log_config()
        else:
            raise TypeError("status must be of type logger.Status")

    def _update_config(self):
        now = datetime.now()
        date = now.strftime("%d/%m/%Y")
        time = now.strftime("%H:%M:%S")
        omegaconf.OmegaConf.set_struct(self.config, True)
        with omegaconf.open_dict(self.config):
            self.config.system.hostname = socket.gethostname()
            self.config.system.process_id = os.getpid()
            self.config.logs.log_id = self._run_id
            self.config.logs.path = os.path.join(self._root, str(self._run_id))
            self.config.system.date = date
            self.config.system.time = time
            self.config.system.status = Status.STARTING.name
        omegaconf.OmegaConf.set_struct(self.config, False)

    def  _update_scheduler_job_id(self, job_id):

        omegaconf.OmegaConf.set_struct(self.config, True)
        with omegaconf.open_dict(self.config):
            self.config.system.scheduler_job_id = job_id
        omegaconf.OmegaConf.set_struct(self.config, False)


    def _log_metrics_key(self,metrics_dict, file_name="metrics"):
        new_keys = []
        for key in metrics_dict.keys():
            if key not in self._metric_dict_keys:
                new_keys.append(key)
        self._metric_dict_keys += new_keys
        dict_file = {key: "" for key in new_keys}
        keys_dir = os.path.join(self._run_dir, '.keys')
        os.makedirs(keys_dir, exist_ok=True)
        file_name = os.path.join(keys_dir , file_name)
        cur_yaml = {}
        try:
            with open(file_name + ".yaml", "r") as f:
                cur_yaml = yaml.safe_load(f)
        except:
            pass
        cur_yaml.update(dict_file)
        with open(file_name + ".yaml", "w") as f:
            yaml.dump(cur_yaml, f)  

    def _set_scheduler_job_id(self):
        abs_name = os.path.join(self._run_dir, "metadata.yaml")
        if os.path.isfile(abs_name):
            with open(abs_name, "r") as file:
                configs = yaml.safe_load(file)
                if "scheduler_job_id" in configs["system"]:
                    omegaconf.OmegaConf.set_struct(self.config, True)
                    with omegaconf.open_dict(self.config):
                        self.config.system.scheduler_job_id = configs["system"][
                            "scheduler_job_id"
                        ]
                    omegaconf.OmegaConf.set_struct(self.config, False)



def DictConfig_to_dict(config: omegaconf.dictconfig.DictConfig)-> ConfigDict:
    """
    Converts an instance of the class omegaconf.dictconfig.DictConfig
    to a dictionary
    
    :param config: The metadata for the run in immutable form
    :type config: omegaconf.dictconfig.DictConfig
    :rtype: Dict[str, Any]
    :return: The metadata for the run in mutable form
    """


    done = False
    out_dict = {}
    for key, value in config.items():
        if isinstance(value, omegaconf.dictconfig.DictConfig):
            out_dict[key] = config_to_dict(value)
        else:
            out_dict[key] = value
    return ConfigDict(out_dict)

def _make_run_dir(_id, root):
    os.makedirs(root, exist_ok=True)
    log_dir = None
    if _id is None:
        fail_count = 0
        while log_dir is None:
            try:
                _id = _maximum_existing_run_id(root) + 1
                log_dir_tmp = os.path.join(root, str(_id))
                os.mkdir(log_dir_tmp)
                log_dir = log_dir_tmp # set log_dir only if successful creation
            except FileExistsError:  # Catch race conditions
                sleep(random.random())
                if fail_count < 1000:
                    fail_count += 1
                else:  # expect that something else went wrong
                    raise
    else:
        log_dir = os.path.join(root, str(_id))
        os.makedirs(root, exist_ok=True)
    return _id, log_dir


def _maximum_existing_run_id(root):
    dir_nrs = [
        int(d)
        for d in os.listdir(root)
        if os.path.isdir(os.path.join(root, d)) and d.isdigit()
    ]
    if dir_nrs:
        return max(dir_nrs)
    else:
        return 0


