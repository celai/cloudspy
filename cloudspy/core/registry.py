class Registry:
    def __init__(self):
        self._modules = []

    def register(self, module):
        self._modules.append(module)
        return module

    def extend(self, modules):
        for module in modules:
            self.register(module)

    def all(self):
        return list(self._modules)

    def valid(self, position):
        return 1 <= position <= len(self._modules)

    def get(self, position):
        return self._modules[position - 1]

    def __len__(self):
        return len(self._modules)
