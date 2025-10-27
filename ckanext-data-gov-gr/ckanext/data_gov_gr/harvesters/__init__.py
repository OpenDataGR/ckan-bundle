# encoding: utf-8

# Import the base harvester
from ckanext.data_gov_gr.harvesters.base import DataGovGrHarvester

# Import the specific harvesters
from ckanext.data_gov_gr.harvesters.growthfund import GrowthFundHarvester

__all__ = [
    'DataGovGrHarvester',
    'GrowthFundHarvester',
]