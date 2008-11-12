#
# Copyright (C) 2008 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import getpass
import os
import sys
from tempfile import mkstemp

from codereview.proto_client import HttpRpc, Proxy
from codereview.review_pb2 import ReviewService_Stub
from codereview.upload_bundle_pb2 import *
from git_command import GitCommand
from error import UploadError

try:
  import readline
except ImportError:
  pass

MAX_SEGMENT_SIZE = 1020 * 1024

def _GetRpcServer(email, server, save_cookies):
  """Returns an RpcServer.

  Returns:
    A new RpcServer, on which RPC calls can be made.
  """

  def GetUserCredentials():
    """Prompts the user for a username and password."""
    e = email
    if e is None:
      e = raw_input("Email: ").strip()
    password = getpass.getpass("Password for %s: " % e)
    return (e, password)

  # If this is the dev_appserver, use fake authentication.
  lc_server = server.lower()
  if lc_server == "localhost" or lc_server.startswith("localhost:"):
    if email is None:
      email = "test@example.com"
    server = HttpRpc(
        server,
        lambda: (email, "password"),
        extra_headers={"Cookie":
                       'dev_appserver_login="%s:False"' % email})
    # Don't try to talk to ClientLogin.
    server.authenticated = True
    return server

  if save_cookies:
    cookie_file = ".gerrit_cookies"
  else:
    cookie_file = None

  return HttpRpc(server, GetUserCredentials,
                 cookie_file=cookie_file)

def UploadBundle(project,
                 server,
                 email,
                 dest_project,
                 dest_branch,
                 src_branch,
                 bases,
                 replace_changes = None,
                 save_cookies=True):

  srv = _GetRpcServer(email, server, save_cookies)
  review = Proxy(ReviewService_Stub(srv))
  tmp_fd, tmp_bundle = mkstemp(".bundle", ".gpq")
  os.close(tmp_fd)

  srcid = project.bare_git.rev_parse(src_branch)
  revlist = project._revlist(src_branch, *bases)

  if srcid not in revlist:
    # This can happen if src_branch is an annotated tag
    #
    revlist.append(srcid)
  revlist_size = len(revlist) * 42

  try:
    cmd = ['bundle', 'create', tmp_bundle, src_branch]
    cmd.extend(bases)
    if GitCommand(project, cmd).Wait() != 0:
      raise UploadError('cannot create bundle')
    fd = open(tmp_bundle, "rb")

    bundle_id = None
    segment_id = 0
    next_data = fd.read(MAX_SEGMENT_SIZE - revlist_size)

    while True:
      this_data = next_data
      next_data = fd.read(MAX_SEGMENT_SIZE)
      segment_id += 1

      if bundle_id is None:
        req = UploadBundleRequest()
        req.dest_project = str(dest_project)
        req.dest_branch = str(dest_branch)
        for c in revlist:
          req.contained_object.append(c)
        for change_id,commit_id in replace_changes.iteritems():
          r = req.replace.add()
          r.change_id = change_id
          r.object_id = commit_id
      else:
        req = UploadBundleContinue()
        req.bundle_id = bundle_id
        req.segment_id = segment_id

      req.bundle_data = this_data
      if len(next_data) > 0:
        req.partial_upload = True
      else:
        req.partial_upload = False

      if bundle_id is None:
        rsp = review.UploadBundle(req)
      else:
        rsp = review.ContinueBundle(req)

      if rsp.status_code == UploadBundleResponse.CONTINUE:
        bundle_id = rsp.bundle_id
      elif rsp.status_code == UploadBundleResponse.RECEIVED:
        bundle_id = rsp.bundle_id
        return bundle_id
      else:
        if rsp.status_code == UploadBundleResponse.UNKNOWN_PROJECT:
          reason = 'unknown project "%s"' % dest_project
        elif rsp.status_code == UploadBundleResponse.UNKNOWN_BRANCH:
          reason = 'unknown branch "%s"' % dest_branch
        elif rsp.status_code == UploadBundleResponse.UNKNOWN_BUNDLE:
          reason = 'unknown bundle'
        elif rsp.status_code == UploadBundleResponse.NOT_BUNDLE_OWNER:
          reason = 'not bundle owner'
        elif rsp.status_code == UploadBundleResponse.BUNDLE_CLOSED:
          reason = 'bundle closed'
        elif rsp.status_code == UploadBundleResponse.UNAUTHORIZED_USER:
          reason = ('Unauthorized user.  Visit http://%s/hello to sign up.'
                    % server)
        elif rsp.status_code == UploadBundleResponse.UNKNOWN_CHANGE:
          reason = 'invalid change id'
        elif rsp.status_code == UploadBundleResponse.CHANGE_CLOSED:
          reason = 'one or more changes are closed'
        else:
          reason = 'unknown error ' + str(rsp.status_code)
        raise UploadError(reason)
  finally:
    os.unlink(tmp_bundle)
