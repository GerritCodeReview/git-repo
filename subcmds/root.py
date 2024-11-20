from command import Command


class Root(Command):
    def Execute(self, opt, args):
        print(self.manifest.topdir)
