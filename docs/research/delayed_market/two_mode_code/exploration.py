"""Independent exploration schedules across fitting rounds and rollout steps."""
from dataclasses import dataclass, asdict
import math

@dataclass(frozen=True)
class ExplorationSchedule:
    mode: str = 'both'
    constant: float = .30
    first: float = .50
    last: float = .10
    round_decay: float = .50
    floor: float = .05

    def __post_init__(self):
        if self.mode not in ('fixed','rounds','timeline','both'):
            raise ValueError('mode must be fixed, rounds, timeline, or both')
        for name in ('constant','first','last','round_decay','floor'):
            value=getattr(self,name)
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f'{name} must be a finite probability in [0,1]')
        if self.first < self.last:raise ValueError('first must be >= last')
        if self.floor > min(self.constant,self.last):
            raise ValueError('floor must not exceed constant or last')

    def probability(self,round_index,step_index,steps):
        if not isinstance(round_index,int) or round_index < 0:raise ValueError('round_index must be a nonnegative integer')
        if not isinstance(steps,int) or steps < 1 or not isinstance(step_index,int) or not 0 <= step_index < steps:
            raise ValueError('step_index must identify a decision within a nonempty rollout')
        if self.mode in ('timeline','both'):
            fraction=step_index/(steps-1) if steps > 1 else .5
            p=self.first+(self.last-self.first)*fraction
        else:p=self.constant
        if self.mode in ('rounds','both'):p*=self.round_decay**round_index
        return min(1.,max(self.floor,p))

    def to_dict(self):return asdict(self)

    def table(self,rounds,steps=10):
        return [dict(round=r+1,step=i,steps=steps,probability=self.probability(r,i,steps))
                for r in range(rounds) for i in range(steps)]

LEGACY_SCHEDULE=ExplorationSchedule(mode='fixed')
