import numpy as np
import pandas as pd
from tqdm import tqdm
from random import *
import pickle
import os
from functools import partial


class GuideEnv:
    '''Stores labeled sequences, reserving some for validation, and runs agents on them.'''

    def __init__(self, batch=1000, validation=0.2, pretrain=False, nocorr=False):
        '''Initialize environment.
        files: csv files to read data from
        batch: number of sequences selected per action
        validation: portion of sequences to save for validation
        initial: pretrain on given datafile
        nocorr: do not compute correlations when running
        '''
        assert 0 <= validation < 1
        files=[f'data/DeepCRISPR/{f}' for f in os.listdir('data/DeepCRISPR') if f.endswith('.csv')]
        initial = 'data/Azimuth/azimuth_preds.csv.gz' if pretrain else None
        dfs = list(map(pd.read_csv, files))
        data = [(strand + seq, score) for df in dfs
            for _, strand, seq, score in 
            df[['Strand', 'sgRNA', 'Normalized efficacy']].itertuples()]
        self.len = len(data[0][0])
        shuffle(data)
        r = int(validation * len(data))
        self.env = dict(data[r:])
        self.val = tuple(np.array(x) for x in zip(*data[:r]))
        self.nocorr = nocorr
        # start agent with some portion of initial sequences
        if initial:
            df = pd.read_csv(initial, delimiter=r'\t', engine='python', compression='gzip')
            azimuth_guides = ['+' + s[6:-3].upper() for s, pam in zip(df.guide_seq, df.pam_seq) if pam == 'GG']
            self.prior = dict([*zip(azimuth_guides, df.azimuth_pred)])
        else:
            self.prior = {}
        self.batch = batch
        assert batch < len(self.env)
        
    def run(self, Agent, cutoff, name, pos):
        '''Run agent, getting batch-sized list of actions (sequences) to try,
        and calling observe with the labeled sequences until all sequences
        have been tried (or the batch number specified by the cutoff parameter
        has been reached). Returns the validation performance after each batch
        (measured using Pearson correlation with the agent's predict method 
        on validation data), as well as the average performance of the best 
        10 guides the agent has seen after each batch. The name and pos
        parameters are used for a progress bar.
        '''
        data = self.env.copy()
        if cutoff is None:
            cutoff = 1 + len(data) // self.batch
        pbar = tqdm(total=min(len(data) // self.batch * self.batch, cutoff * self.batch), 
                        position=pos, desc=name)
        agent = Agent(self.prior.copy(), self.len, self.batch)
        seen = []
        corrs = []
        top10 = []
        regret = []
        while len(data) >= self.batch and (cutoff is None or len(top10) < cutoff):
            sampled = agent.act(list(data.keys()))
            assert len(set(sampled)) == self.batch, "bad action"
            agent.observe({seq: data[seq] for seq in sampled})
            regret.append(([0.] + regret)[-1] + \
                    sum(sorted(data.values())[-self.batch:]) - sum(data[seq] for seq in sampled))
            for seq in sampled:
                seen.append(data[seq])
                del data[seq]
            if not self.nocorr:
                predicted = np.array(agent.predict(self.val[0].copy()))
                corrs.append(np.nan_to_num(np.corrcoef(predicted, self.val[1])[0, 1]))
            top10.append(np.array(sorted(seen))[-10:].mean())
            pbar.update(self.batch)
        pbar.close()
        return np.array(corrs), np.array(top10), np.array(regret)


class FlankEnv(GuideEnv):
    '''Simpler environment using flanking sequences.'''

    def __init__(self, batch, validation, pretrain=False, nocorr=False):
        df = pickle.load(open('data/flanking_sequences/cbf1_reward_df.pkl', 'rb'))
        data = [*zip([f'+{x}' for x in df.index], df.values)]
        shuffle(data)
        dlen = 10000
        self.prior = dict(data[dlen:]) if pretrain else {}
        data = data[:dlen]
        r = int(dlen * validation)
        self.env = dict(data[r:])
        self.val = tuple(np.array(x) for x in zip(*data[:r]))
        self.len = len(data[0][0])
        self.batch = batch
        self.nocorr = nocorr


class _GenericEnv(GuideEnv):

    def __init__(self, data, prior, batch, validation, pretrain=False, nocorr=False):
        data = pd.read_csv(data, header=None)
        prior = pd.read_csv(prior, header=None) if pretrain and prior is not None else None
        self.prior = dict(prior.values if prior is not None else [])
        data = data.values
        r = int(len(data) * validation)
        self.env = dict(data[r:])
        self.val = tuple(np.array(x) for x in zip(*data[:r]))
        self.batch = batch
        self.nocorr = nocorr
        self.len = len(data[0][0])


def GenericEnv(data, prior=None):
    '''Parameterized environment built with arbitrary csv [sequence, score]
    data and pretraining data files.
    '''
    return partial(_GenericEnv, data, prior)

