# Copyright (C) 2013 The Android Open Source Project.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

  $ export REPO=${TESTDIR}/../repo
  $ export TOP=$(pwd)

Create the test set:

  $ mkdir -p ${TOP}/server/manifest
  $ cd ${TOP}/server/manifest
  $ git init --bare
  Initialized empty Git repository in * (glob)
  $ mkdir -p ${TOP}/server/something
  $ cd ${TOP}/server/something
  $ git init --bare
  Initialized empty Git repository in * (glob)



Populate the test set:

  $ mkdir -p cl
  $ mkdir -p ${TOP}/set
  $ cd ${TOP}/set
  $ git clone ${TOP}/server/manifest
  Cloning into 'manifest'...
  warning: You appear to have cloned an empty repository.
  done.
  $ cd manifest
  $ cat > default.xml << EOF
  > <?xml version="1.0" encoding="UTF-8"?>
  > <manifest>
  >  <remote fetch="." name="bla"/>
  >  <default remote="bla" revision="master" sync-j="4"/>
  >  <project groups="default" name="something"/>
  > </manifest>
  > EOF
  $ git add default.xml
  $ git commit -m 'hello there'
  [master *] hello there (glob)
   1 file changed, 6 insertions(+)
   create mode 100644 default.xml
  $ git push origin HEAD:master
  To */server/manifest (glob)
   * [new branch]      HEAD -> master
  $ cd ${TOP}/set
  $ git clone ${TOP}/server/something
  Cloning into 'something'...
  warning: You appear to have cloned an empty repository.
  done.
  $ cd ${TOP}/set/something
  $ echo mememe > main.c
  $ git add main.c
  $ git commit -m 'weird code'
  [master *] weird code (glob)
   1 file changed, 1 insertion(+)
   create mode 100644 main.c
  $ git push origin HEAD:master
  To */server/something (glob)
   * [new branch]      HEAD -> master



Init a client:

  $ cd ${TOP}
  $ mkdir roclient
  $ cd roclient
  $ ${REPO} init --repo-url ${TESTDIR}/../ --no-repo-verify -u ${TOP}/server/manifest 2>&1 | grep --invert-match 'new tag'
  Get * (glob)
  From * (glob)
   * [new branch]      cram       -> origin/cram
  Get */server/manifest (glob)
  From */server/manifest (glob)
   * [new branch]      master     -> origin/master
  
  repo has been initialized in * (glob)

Repo sync

  $ ${REPO}  sync --no-repo-verify
  From * (glob)
   * [new branch]      master     -> bla/master
  
  Fetching project something

  $ ls
  something
  $ ls something
  main.c


Have an rw client for making changes:

  $ cd ${TOP}
  $ mkdir rwclient
  $ cd rwclient
  $ ${REPO}  init --repo-url ${TESTDIR}/../ -u ${TOP}/server/manifest 2>/dev/null
  
  repo has been initialized in * (glob)
  $ ${REPO}  sync 2>/dev/null
  Fetching project something

Make a change:

  $ ${REPO} start iLoveCoffee --all
  $ echo bla >> something/main.c
  $ cd something
  $ git commit -a -m 'there will be cake'
  [iLoveCoffee *] there will be cake (glob)
   1 file changed, 1 insertion(+)


Upload the change:


  $ git branch
  * iLoveCoffee

#repo doesn't exit, so i can't test this one
#  $ repo upload .
#  error: upload aborted by user
#  Upload project something/ to remote branch master:
#    branch iLoveCoffee * (glob)
#           * there will be cake (glob)
#  to does.not.exist (y/N)?



Lets assume we went through gerrit:

  $ git push bla iLoveCoffee:master
  To */server/something (glob)
     * iLoveCoffee -> master (glob)
  $ git branch
  * iLoveCoffee
  $ ${REPO}  abandon iLoveCoffee
  Abandoned in 1 project(s):
    something
  $ git branch
  * (no branch)



Now pull the thing

  $ cd ${TOP}/roclient
  $ ${REPO} sync
  From */server/something (glob)
     * master     -> bla/master (glob)
  
  Fetching project something
  $ cd something
  $ grep bla main.c
  bla
