#!/bin/bash


HYDRA_FULL_ERROR=1   OC_CAUSE=1 python -m ipdb main.py  \
                +mlxpy.use_scheduler=False\
                +mlxpy.use_version_manager=True\
                +mlxpy.use_logger=True\
