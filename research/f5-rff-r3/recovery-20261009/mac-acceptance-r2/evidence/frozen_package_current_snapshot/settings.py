from .common import ROOT,read_json
from .features import PATH_FEATURES
BASE_FEATURES=read_json(ROOT/'config/base_features.json')
FEATURES=BASE_FEATURES+PATH_FEATURES
CONTRACT=read_json(ROOT/'config/contract.json')
PARAMS=CONTRACT['learner']['params']
ROUNDS=CONTRACT['learner']['rounds']
