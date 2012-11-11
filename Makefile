PREFIX = /usr/local
DESTDIR =
INSTALL = install
LN = ln -s
RM = rm -f
RMDIR = rmdir

NAME = git-repo
SHAREFILES = repo git_ssh  $(wildcard *.py) $(wildcard subcmds/*.py) $(wildcard hooks/*)
SHARESUBDIRS = subcmds hooks
SHAREDIR = $(DESTDIR)$(PREFIX)/share/$(NAME)
PYFILES = $(wildcard *.py) $(wildcard subcmds/*.py)
PYCFILES = repoc $(PYFILES:.py=.pyc) $(PYFILES:.py=.pyo)
DOCFILES = COPYING SUBMITTING_PATCHES $(wildcard docs/*.txt)
DOCDIR = $(DESTDIR)$(PREFIX)/share/doc/$(NAME)
BINFILES = repo
BINDIR = $(DESTDIR)$(PREFIX)/bin

.PHONY: all install uninstall clean

all:
	@echo "To install Repo in $(DESTDIR)$(PREFIX) type: make install"

install: $(SHAREFILES) $(DOCFILES)
	$(foreach f,$(SHAREFILES),$(INSTALL) -D -m 0755 $f $(SHAREDIR)/$f &&) true
	$(INSTALL) -d $(BINDIR)
	$(foreach f,$(BINFILES),$(LN) $(SHAREDIR)/$f $(BINDIR)/$f &&) true
	$(INSTALL) -d $(DOCDIR)
	$(INSTALL) -D -m 0644 $(DOCFILES) $(DOCDIR)

uninstall:
	$(RM) $(foreach f,$(SHAREFILES),$(SHAREDIR)/$f)
	$(RM) $(foreach f,$(PYCFILES),$(SHAREDIR)/$f)
	$(RMDIR) $(foreach d,$(SHARESUBDIRS),$(SHAREDIR)/$d) $(SHAREDIR)
	$(RM) $(foreach f,$(BINFILES),$(BINDIR)/$(notdir $f))
	$(RM) $(foreach f,$(DOCFILES),$(DOCDIR)/$(notdir $f))
	$(RMDIR) $(DOCDIR)

clean:
	$(RM) $(PYCFILES)
