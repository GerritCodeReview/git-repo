import os
import unittest

import manifest_xml
import git_config

def fixture(*paths):
  """Return a path relative to test/fixtures.
  """
  return os.path.join(os.path.dirname(__file__), 'fixtures', *paths)

class mockProject():
  def __init__(self):
    class branch():
      def __init__(self):
        self.merge = "bar"
    self.branch = branch()
    self.worktree = "."
    config_fixture = fixture('manifest_config')
    self.config = git_config.GitConfig(config_fixture)


  def CurrentBranch(self):
    return "foo"

  def GetBranch(self, branch):
    return self.branch

class XmlManifestUnitTest(unittest.TestCase):

  def setUp(self):
    manifest_fixture = fixture()
    self.manifest = manifest_xml.XmlManifest(manifest_fixture)
    self.manifest.manifestProject = mockProject()


  def test_remote(self):
    """
    """
    self.assertEqual(self.manifest.remotes['repo-root'].ToRemoteSpec('project').url,
                     'https://url:8080/project')
    self.assertEqual(self.manifest.remotes['repo-parent'].ToRemoteSpec('project').url,
                     'https://url:8080/path1/project')
    self.assertEqual(self.manifest.remotes['repo-current'].ToRemoteSpec('project').url,
                     'https://url:8080/path1/path2/project')
    self.assertEqual(self.manifest.remotes['repo-empty'].ToRemoteSpec('project').url,
                     'https://url:8080/path1/path2/path3/project')

    self.assertEqual(self.manifest.remotes['repo-empty'].ToRemoteSpec('/project').url,
                     'https://url:8080/path1/path2/path3//project')

    self.assertItemsEqual([xx.remote.url for xx in self.manifest.projects],
                          [
                              'https://url:8080/path1/project1',
                              'https://url:8080/path1/path2/path3/project2',
                          ])

if __name__ == '__main__':
  unittest.main()
