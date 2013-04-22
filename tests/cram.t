In order to run this test, you need cram https://bitheap.org/cram/
$ pip install cram
and this git repo (the one for repo. i.e. where this file is in),
needs to have a local branch called 'stable' which was signed.
$ git checkout -b stable remotes/origin/stable

then just run 'cram cram.t'
it won't output anything useful, except either that nothing failed,
or it will hang forever, since repo never exits when something is wrong
and cram doesnt print the output before it exits


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
  >   <remote fetch="." name="bla" review='does.not.exist'/>
  >  <default remote="bla" revision="master" sync-j="4"/>
  >  <project groups="default" name="something"  />
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
  $ ${REPO} init --repo-url ${TESTDIR}/../ --repo-branch stable -u ${TOP}/server/manifest 2>&1 | grep --invert-match 'new tag'
  Get * (glob)
  From * (glob)
   * [new branch]      master     -> origin/master
   * [new branch]      stable     -> origin/stable
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
