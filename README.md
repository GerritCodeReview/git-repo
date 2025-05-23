
## Contact

Please use the [repo-discuss] mailing list or [issue tracker] for questions.

You can [file a new bug report][new-bug] under the "repo" component.

Please do not e-mail individual developers for support.
They do not have the bandwidth for it, and often times questions have already
been asked on [repo-discuss] or bugs posted to the [issue tracker].
So please search those sites first.

## Install

Many distros include repo, so you might be able to install from there.
```sh
# Debian/Ubuntu.
$ sudo apt-get install repo

# Gentoo.
$ sudo emerge dev-vcs/repo
```

You can install it manually as well as it's a single script.
```sh
$ mkdir -p ~/.bin
$ PATH="${HOME}/.bin:${PATH}"
$ curl https://storage.googleapis.com/git-repo-downloads/repo > ~/.bin/repo
$ chmod a+rx ~/.bin/repo
```


[new-bug]: https://issues.gerritcodereview.com/issues/new?component=1370071
[issue tracker]: https://issues.gerritcodereview.com/issues?q=is:open%20componentid:1370071
[repo-discuss]: https://groups.google.com/forum/#!forum/repo-discuss
