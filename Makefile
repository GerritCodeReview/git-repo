#
# Copyright 2008 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

GERRIT_SRC=../gerrit
GERRIT_MODULES=codereview froofle

all:

clean:
	find . -name \*.pyc -type f | xargs rm -f

update-pyclient:
	$(MAKE) -C $(GERRIT_SRC) release-pyclient
	rm -rf $(GERRIT_MODULES)
	(cd $(GERRIT_SRC)/release/pyclient && \
	 find . -type f \
	 | cpio -pd $(abspath .))
