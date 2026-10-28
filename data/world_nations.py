"""Keep country mappings attached to their explicit world owner."""

import copy


class WorldNations(dict):
    def __init__(self, world, values=()):
        super().__init__(values)
        self.world = world

    def __copy__(self):
        # Standalone projections must not retain authority over their source world.
        return dict(self)

    def __deepcopy__(self, memo):
        result = {}
        memo[id(self)] = result
        result.update(copy.deepcopy(dict(self), memo))
        return result
