"""
Utilities to interface with JIRA from Houdini.

prb (Peter Bowmar) Feb 4, 2015 on INVERT
updated Feb 2, 2016 on SITE. Wow, a year later!

aru (Allen Ruilova) Refactor to use ticket_creator module:
file:///tools/SITE/doc/TicketCreator/TicketCreator/index.html

Currently includes function(s) to submit tickets from RMB menu on SOPs
called from OPmenu or from Dneg defined Shelf tools
"""

# standard Python modules
from collections import namedtuple
import pwd

# dneg modules
from dnhoufuncs import logging

# SESI supplied modules
import hou

# import TicketInfo
from jiraticketsubmitter import TicketInfo

import ticket_creator

# local modules
from .HipFileUtils import *
from .HouJiraReportDialog import DN_TICKET_DESCRIPTION_MESSAGE
from .HouJiraReportDialog import DN_TICKET_TITLE_MESSAGE

# globals
DN_TOOLS_SITE = "/tools/SITE/data/houdini"
DN_WATCHERS_FILE = "houdiniJiraWatchers.dat"

# current keeper of the tool and primary watcher
DN_HOUDINI_JIRA_MASTER_LOGIN = "aru"  # Allen Ruilova

# default site wide support project to use
DN_HOUDINI_SUPPORT_PROJECT = "PTSUP"

# job logger
DN_JIRA_SUBMIT_LOG = logging.getLogger(module="ticket_creator.pipepkg_tools")

# use named tuple to store session info auto generated in houdini
AutoInfo = namedtuple("AutoInfo", ["location", "shot", "submitteditem", "opdefinitiontype",
                                   "opdefinitionpath", "orighippath", "houdiniversion",
                                   "codeline1", "houdinipath", "curtools", "bobpaths", "codeline2"])


# ----------------------------------------------------
# classes defined for this module
# ----------------------------------------------------


class HoudiniTicket(ticket_creator.Ticket):
    """Main class to generate jira dialog object, gather relevant info and submit the ticket."""

    # noinspection PyBroadException
    def __init__(self, **kwargs):
        """
        Do initial setup and then present the UI via the panel.

        NOTE: Generic houdini ticket can launched from DNEG Menu:
        /tools/SITE/houdini/16.0/MainMenuCommon.xml
        or
        ./site-tdtools/dependencies/houdini/MainMenuCommon_skeleton.xml

        To test inside of Houdini in a python shell:

            node ticket:
            from jiraticketsubmitter.HoudiniTicket import *
            from jiraticketsubmitter.HouJiraReportDialog import *
            node = hou.node('/obj/geo1/geomInV21')
            submitter = HoudiniTicket(item=node, disable_ui=True)
            dialog = HouJiraReportDialog(**submitter.info_for_dialog)
            dialog.set_title_and_comment(title='non-ui test', comment='test submitter from python shell')
            dialog.create_ticket(save_hip=False)  # set save_hip=True to save a copy of the hip file

            generic ticket:
            from jiraticketsubmitter.HoudiniTicket import *
            from jiraticketsubmitter.HouJiraReportDialog import *
            submitter = HoudiniTicket()

        Args:
            **kwargs: Arbitrary keyword arguments.
            kwargs["item"] (hou.Node or hou.Tool): node or tool to open a ticket for, to be passed to panel script.
            kwargs["item_parent"] (hou.Shelf): in case of a shelf tool, this is the parent shelf.
            kwargs["pane_tab"] (hou.PaneTab): pane tab window that is creating an instance of this class.
            kwargs["disable_ui"] (bool): force turn off ui mode so ticket can be created from python shell.
            kwargs["jira_server"] (str): name of jira server to use

        Raises:
            ticket_creator.TicketCreatorException: general ticket creator exception
            TypeError: if ticket created is invalid.
            KeyError: if user of tool has an invalid user name. (actually does a 'pass' rather than raise)
            AssertionError: if there are no valid watchers for this ticket
            hou.OperationFailed: any houdini specific exception

        """
        # get kwargs
        self._hou_issue_item = kwargs['item'] if 'item' in kwargs else None
        self._hou_issue_parent = kwargs['item_parent'] if 'item_parent' in kwargs else None
        self._pane_tab = kwargs['pane_tab'] if 'pane_tab' in kwargs else None
        self._is_ui = not kwargs['disable_ui'] if 'disable_ui' in kwargs else hou.isUIAvailable()
        self._jira_server = kwargs['jira_server'] if 'jira_server' in kwargs else 'jira'

        # first make sure we have a proper jira connection
        try:
            ticket_creator.ext.jira.tools.get_jira_connection(server=self._jira_server)
        except:
            raise ticket_creator.TicketCreatorException("Error: ticket_creator could not get connection to "
                                                        "JIRA server '{0}'".format(self._jira_server))

        # store info about jira submission
        self._auto_info = None

        # my member vars
        self._hou_issue_type = ""
        self._final_jira_description = ""

        # initial people copied as watchers on all houdini issues
        # this is augmented with a file called "houdiniJiraWatchers.dat" which
        # is a simple list of logins, one per line. This lives in:
        # /tools/JOBNAME/data/houdini/houdiniJiraWatchers.dat

        # Update _all_issues_watchers with any entries found default issue watcher should be the master
        self._all_issues_watchers = []
        try:
            pwd.getpwnam(DN_HOUDINI_JIRA_MASTER_LOGIN)
            self._all_issues_watchers = [DN_HOUDINI_JIRA_MASTER_LOGIN]
        except KeyError:
            pass

        # get additional watchers beyond jira master
        self._search_for_watchers()
        try:
            assert self._all_issues_watchers
        except AssertionError:
            raise

        # Immediately exit if houdini env is not properly set (legacy)
        if "HOUDINI_MAJOR_RELEASE" not in os.environ:
            raise hou.OperationFailed("HOUDINI_MAJOR_RELEASE variable not found!")

        # ==================================================
        # Do the work

        try:
            # init ticket creator stuff
            super(HoudiniTicket, self).__init__()

            # check item for issue type and set appropriate project to send ticket to
            self._check_item()

            # get auto generated information
            self._get_auto_info()

            # get final description info
            self._build_final_description()

            # create ticket
            self._create_hou_ticket()

            # create dialog info dict
            self.info_for_dialog = {"ticket": self,
                                    "pane_tab": self._pane_tab,
                                    "final_jira_description": self._final_jira_description,
                                    "jira_server": self._jira_server,
                                    "parent": None,
                                    "disable_ui": not self._is_ui}

        except hou.OperationFailed:
            raise

    def _create_hou_ticket(self):
        """Create ticket object.

        First using defaults then set the inital comment to final description data populated from _auto_info dict.

        Raises:
            hou.OperationFailed: no SHOW environ var available, not in a proper show/shot environment
        """
        # initial default ticket values
        self.title = DN_TICKET_TITLE_MESSAGE
        self.issue_type = 'Bug'
        self.labels.append('houdini')
        self.comment = DN_TICKET_DESCRIPTION_MESSAGE
        self.components.append('Houdini')

        # set reporter and show info
        try:
            # reporter and watchers
            user = os.environ["USER"]
            self.reporter = user
            self.watchers = self._all_issues_watchers

            # show
            self.shows.append(os.environ["SHOW"])
        except KeyError:
            msg = 'Missing USER or SHOW environment variable.\nHave you run dnshow?'
            raise hou.OperationFailed(msg)

    def _search_for_watchers(self):
        """Search for files called "houdiniJiraWatchers.dat" which are a simple list of logins, one per line.

        This lives in:/tools/JOBNAME/data/houdini/houdiniJiraWatchers.dat

        Any found are added to self._allIssuesWatchers, unless the login
        is already part of the list.

        Raises:
            KeyError: if user of tool has an invalid user name. (actually does a 'pass' rather than raise)

        """
        # Currently this searches on the current job and SITE, this can be expanded in future possibly to sequences or
        # even shots
        search_locations = [DN_TOOLS_SITE, os.path.join(os.sep, "tools", os.environ["SHOW"], "data", "houdini")]

        # get my current site
        site_name = dnsitedata.local_site().short_name

        # Append other search locations here in future...
        #    as of this writing I don't see a 'data' dir by default
        #    on seq or shot so I expect some discussion around this

        line = re.compile(r"^(?P<login>[a-zA-Z0-9_-]+)"
                          r"\W+(?P<sites>([a-zA-Z0-9_-]+[:]*)*[a-zA-Z0-9_-]*)\W+"
                          r"(?P<First>[a-zA-Z0-9_-]+)"
                          r"\W+"
                          r"(?P<Last>[a-zA-Z0-9_-]+)")

        # iterate the list
        for curloc in search_locations:
            path = os.path.join(os.sep, curloc, DN_WATCHERS_FILE)
            # test that a config file exists there
            if not (os.path.isfile(path) and os.access(path, os.R_OK)):
                continue

            # open file and generate list of valid users
            with open(path, "r") as _file:
                groups = [line.search(x) for x in _file.readlines()]
                for _ in [x.group('login') + ',' + x.group('sites') for x in groups if x is not None]:
                    user = re.split(",", _)[0]
                    sites = re.split(":", re.split(",", _)[1])

                    # make sure current site_name is in list of valid sites for this user (empty site list is 'all')
                    if not sites[0] or site_name in sites:
                        # test for valid login.
                        try:
                            assert pwd.getpwnam(user)
                            # append to self._all_issues_watchers
                            if user not in self._all_issues_watchers:
                                self._all_issues_watchers.append(user)

                        except KeyError:
                            # invalid, just skip it and print message
                            message = "In file: {0}\nInvalid user login: {1}".format(path, user)
                            print message

    def _check_item(self):
        """See what the item is that the Jira ticket should be submitted on.

        Currently handles a Node or a hou.Tool (shelf tool) or if None
        is a generic submission.

        """

        def _set_support_project_and_group(item, is_node=True):
            """Check the install path of otl to determine the show release location, set the support
            group to 'pipe_td' if the show release is not SITE.

            Args:
                item (hou.Node): node to check
                is_node (bool): True = hou.Node, False = hou.Tool

            Returns (str): group to use

            """
            # default project is PTSUP, set group to 'rnd_houdini'
            self.project = DN_HOUDINI_SUPPORT_PROJECT
            group = 'rnd_houdini'

            # set regex for testing
            show_re = re.compile(r"/tools/(?P<show>[a-zA-Z0-9_-]+)")

            # get path
            path = item.type().definition().libraryFilePath() if is_node else item.filePath()

            # test path
            g = show_re.search(path)
            if g and g.group('show') != 'SITE':
                group = 'pipe_td'

            return group

        # case where it's a hou.Node (or subclass, usually)
        if isinstance(self._hou_issue_item, hou.Node):
            self.group = _set_support_project_and_group(self._hou_issue_item)
            self._hou_issue_type = "dneg_node"

        # case where it's a hou.Tool (or subclass, potentially)
        elif isinstance(self._hou_issue_item, hou.Tool):
            self.group = _set_support_project_and_group(self._hou_issue_item, is_node=False)
            self._hou_issue_type = "dneg_tool"

        # case where it's just generic and will capture whatever it can
        else:
            self.project = DN_HOUDINI_SUPPORT_PROJECT
            self.group = 'rnd_houdini'
            self._hou_issue_type = "generic"

    def _get_auto_info(self):
        """Collect various bits of info from the environment and Houdini to automatically add to the Jira ticket."""
        hpath_info = "Submission HIP location:\n{0}\n\n".format(hou.getenv('HIP'))

        # take the whole HOUDINI_PATH too
        hpath = "HOUDINI_PATH: \n"
        for loc in os.environ['HOUDINI_PATH'].split(":"):
            hpath += "{0}\n".format(loc)

        # ---------------------------------------------------------------------
        # stuff to go into final description

        self._auto_info = AutoInfo(
            location=TicketInfo.get_location_info(),
            shot=TicketInfo.get_shot_info(),
            submitteditem=TicketInfo.get_item_info(self._hou_issue_type, self._hou_issue_item, self._hou_issue_parent),
            opdefinitiontype=TicketInfo.get_item_type_info(self._hou_issue_type, self._hou_issue_item),
            opdefinitionpath=TicketInfo.get_item_path_info(self._hou_issue_type, self._hou_issue_item),
            orighippath=hpath_info,
            houdiniversion=TicketInfo.get_houdini_version_info(),
            codeline1="{code:collapse=true|title=Environment Info Below} ",
            houdinipath=hpath,
            curtools=TicketInfo.get_curtools_info(),
            bobpaths=TicketInfo.get_bob_info(),
            codeline2="{code}")

    def _build_final_description(self):
        """
        Populate the self._final_jira_description variable.

        Basically takes all the auto generated info and tacks it on the end of the user-entered description.

        """
        self._final_jira_description = "{0}\n{1}".format(self._final_jira_description, "-" * 79)
        self._final_jira_description = "{0}\nAUTO GENERATED INFO FOLLOWS".format(self._final_jira_description)
        self._final_jira_description = "{0}\n{1}".format(self._final_jira_description, "-" * 79)

        # iterate over keys in named tuple
        # noqa: The leading underscore on the method name isn't there to discourage use.
        for _, value in self._auto_info._asdict().iteritems():
            if value:
                self._final_jira_description = "{0}\n{1}".format(self._final_jira_description, value)
