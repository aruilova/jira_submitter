"""Module containing class used to create jira report dialog ui."""


# standard Python modules
import os
import Queue
import re
import subprocess
import sys
import threading
import tempfile

# qt stuff
from qtswitch import QtGui
import wizqt.widget.text_edit

# SESI supplied modules
import hou

# local modules
from jiraticketsubmitter import TicketInfo, HipFileUtils

# dneg modules
from ticket_creator import Ticket, exceptions
from ticket_creator.ext.jira import JiraReportDialog, JiraTicketCreator, tools

# init title
DN_TICKET_TITLE_MESSAGE = '< ISSUE SUMMARY REQUIRED >'

# init description
DN_TICKET_DESCRIPTION_MESSAGE = '< ISSUE DESCRIPTION REQUIRED - ** KNOWN BUG w RMB menu (dont use), ' \
                                'USE Ctl-C Ctl-V INSTEAD ** >'

# ----------------------------------------------------
# classes defined for this module
# ----------------------------------------------------


class HouJiraReportDialog(JiraReportDialog):
    """Sub class created to override create clicked behavior in parent class.

    Args:
        **kwargs: Arbitrary keyword arguments.
        kwargs["ticket"] (object): object to report on
        kwargs["parent"] (object): parent dialog if any
        kwargs["disable_ui"] (bool): force turn off ui mode so ticket can be created from python shell
        kwargs["pane_tab"] (object): parent pane_tab object dialog is attached to (None if not in ui mode)
        kwargs["final_jira_description"] (str): full description text to go to ticket

    Raises:
        exceptions.TicketValidationError: raised if ticket is not valid
        AssertionError: raised if ticket we are submitting is not a 'Ticket' object

    """
    # def __init__(self, ticket, creator, parent=None, disable_ui=False):

    def __init__(self, **kwargs):
        """Initialize ticket and creator objects, supporting strings."""
        self._url = None
        self._ticket = kwargs["ticket"] if 'ticket' in kwargs else None
        self._is_ui = not kwargs["disable_ui"] if 'disable_ui' in kwargs else hou.isUIAvailable()
        self._parent = kwargs["parent"] if 'parent' in kwargs else None

        # most likely need public access
        self.pane_tab = kwargs["pane_tab"] if 'pane_tab' in kwargs else None
        self.final_jira_description = kwargs["final_jira_description"] if 'final_jira_description' in kwargs else ''
        self.jira_server = kwargs["jira_server"] if 'jira_server' in kwargs else 'jira'
        self.issue = None
        self.jira = None
        self.save_hip = False
        self.save_hip_toggle = None

        # member widget uiDescriptionTextEdit is overridden later, need to init here first
        self.uiDescriptionTextEdit = None

        # member widget uiWatchersLineEdit is overridden later, need to init here first
        self.uiWatchersLineEdit = None

        # member widget uiSummaryLineEdit is overridden later, need to init here first
        self.uiSummaryLineEdit = None

        # make sure ticket object exists and is typed properly
        try:
            assert self._ticket
            assert isinstance(self._ticket, Ticket)
        except AssertionError:
            raise

        # validate ticket
        try:
            self._ticket_creator = JiraTicketCreator()
            self._ticket_creator.validate(self._ticket)

        except exceptions.TicketValidationError:
            raise

        # init parent if in ui mode
        if self._is_ui:
            # JiraReportDialog __init__ initializes _ticket_creator,
            # sets the connection and validates ticket
            super(HouJiraReportDialog, self).__init__(self._ticket, self._parent)

            # do necessary ui modifications post parent init
            self.uiCreateButton.setText('Create Ticket')

            # post ui creation edits
            self.post_create_main_label()
            self.post_edit_priority_box()
            self.post_edit_type_box()
            self.post_delete_project_combo_box()
            self.post_override_description_text_edit()
            self.post_fix_summary_line_edit()
            self.post_fix_watchers_line_edit()
            self.post_create_save_check_box()

    # create jira ticket
    def create_ticket(self, save_hip=False):
        """Expose the create ticket for use in non-ui mode.

        Args:
            save_hip (bool): copy over save_hip toggle
        """
        self.save_hip = save_hip
        try:
            self._createTicket()
        except:
            raise

    # convenience function to set title and comment
    def set_title_and_comment(self, **kwargs):
        """Set the ticket title and comment in non-ui mode.

        Args:
            **kwargs: Arbitrary keyword arguments.
            kwargs["title"] (str): ticket summary
            kwargs["comment"] (str): ticket description
        """
        if kwargs["title"]:
            self._ticket.title = kwargs["title"]
        if kwargs["comment"]:
            self._ticket.comment = kwargs["comment"]

    def reject(self):
        """Override reject so that when we press 'Cancel' we can kill our parent tab."""
        # just in case the pane tab was not created in the first place
        if not self.pane_tab:
            return

        # find our parent tab object
        name = self.pane_tab.name()
        _pane_tab = hou.ui.findPaneTab(name)
        _pane_tab.setIsCurrentTab()

        # kill our dialog
        super(HouJiraReportDialog, self).reject()

        # now kill parent tab (need to do it in a thread because the desktop manager crashes otherwise)
        if self._is_ui:
            queue = Queue.Queue
            thread = threading.Thread(target=HipFileUtils.kill_pane_tab, args=(queue, _pane_tab))
            thread.daemon = True
            thread.start()

    def _createTicket(self):
        """Log the given ticket in Jira.

        Overriding from parent class.

        Called when the "Create Ticket" button is pressed. New local definition to add hip file saving operations.
        """

        # update ticket info from ui
        if self._is_ui:
            self._updateTicket()

        # exit here if comment (description) or title (summary) is empty
        message = None
        if not self._ticket.title or self._ticket.title == DN_TICKET_TITLE_MESSAGE:
            message = "Please enter a valid issue summary"
        elif not self._ticket.comment or self._ticket.comment == DN_TICKET_DESCRIPTION_MESSAGE:
            message = "Please enter a valid issue description"
        if message:
            if self._is_ui:
                hou.ui.displayMessage(message)
                self.reject()
            else:
                raise hou.OperationFailed(message)
            return

        # prepend reporter to the ticket title
        self._ticket.title = "[{0}] {1}".format(self._ticket.reporter, self._ticket.title)

        # save issue specific hip file
        hip_save_string = "No HIP file supplied. Working Dir is: {0}\n".format(hou.getenv('HIP'))
        if self.save_hip or (self._is_ui and self.save_hip_toggle and self.save_hip_toggle.isChecked()):
            saved_hip, submission_hip_file = HipFileUtils.save_hip()

            # transfer hip file to remote site(s), fail silently
            if saved_hip and submission_hip_file:
                HipFileUtils.transfer_hip(submission_hip_file)
                hip_save_string = "Submission HIP location:\n{0}\n\n".format(submission_hip_file)

        # fix jira description
        self.final_jira_description = re.sub(r"Submission HIP location:\n.*\n\n", hip_save_string,
                                             self.final_jira_description)

        # create ticket and add final description as initial comment
        try:
            self.create_issue()
        except (AssertionError, BaseException):
            raise

    def create_issue(self):
        """Create actual issue."""
        # first let's make a ticket creator object if missing
        self.jira = tools.get_jira_connection(server=self.jira_server)

        # create issue
        self.issue = self._ticket_creator.create(self._ticket)

        # add a comment by connection to ticket issue
        if self.issue:
            if self.final_jira_description:
                self.jira.add_comment(self.issue, self.final_jira_description)

            # attempt to open system browser with the issue for further
            # editing if required, such as adding watchers or attaching
            # other files
            if self._is_ui:
                self._url = 'http://{0}/browse/{1}'.format(self.jira_server, self.issue.key)
                self._open_url()

            print "\n----------------------------------------------"
            print "{0}: Created issue {1}".format(__name__, self.issue.key)
            print "----------------------------------------------\n"

        # DONE, cleanup ui
        if self._is_ui and self.pane_tab:
            # close dialog
            self.close()

            # create message file to notify parent session that submission dialog is done
            # 'wait_jira_submit' spawned by the panel creator is waiting for this file to be created so it can kill
            # the parent pane tab. 'wait_jira_submit' removes the file.
            tmp_file_suffix = "_hou_jira_submit_pane_tab_{0}_{1}".format(self.pane_tab.name(), hou.hipFile.basename())
            tempfile.NamedTemporaryFile(delete=True, suffix=tmp_file_suffix)

        # for future scripting use
        return self.issue

    def _open_url(self):
        """Code copied from stackoverflow to open.

        URL using system default
        """
        if sys.platform == 'win32':
            os.startfile(self._url)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', self._url])
        else:
            try:
                # making Linux a little more robust
                print 'Attempting to open issue: {0}'.format(self._url)
                subprocess.Popen(['xdg-open', self._url])
            except OSError:
                print 'Please open a browser on: {0}'.format(self._url)

    # functions to edit QtDialog post JiraReportDialog init

    def post_create_save_check_box(self):
        """Customize the save hip file checkbox."""
        # set save checkbox
        toggle = QtGui.QCheckBox('SAVE COPY OF HIP FILE FOR TICKET INFO', self)
        toggle.resize(550, 70)

        # set style sheet and icon for the button
        style_sheet = 'QCheckBox {font: bold large "Simplex";' \
                      'color: rgb(0, 185, 20); ' \
                      'font-size: 14px;text-align: center} ' \
                      'QCheckBox::indicator {width: 20px;height: 20px;} '
        toggle.setStyleSheet(style_sheet)
        toggle.setChecked(False)
        # noinspection PyCallByClass,PyTypeChecker
        icon = QtGui.QIcon.fromTheme("drive-harddisk")
        toggle.setIcon(icon)

        # add save hip toggle to same buttonBox as cancel and create buttons
        self.uiButtonBox.addButton(toggle, QtGui.QDialogButtonBox.ActionRole)
        self.save_hip_toggle = toggle

    def post_delete_project_combo_box(self):
        """Get rid of project combo box."""
        project_box = self.uiProjectComboBox
        project_box.close()

    def post_edit_priority_box(self):
        """Re-order priority QComboBox from base module setting first find the desired item then add it in desired
        order."""
        priority_box = self.uiPriorityComboBox
        icon0 = priority_box.itemIcon(priority_box.findText('Minor'))
        icon1 = priority_box.itemIcon(priority_box.findText('Trivial'))
        icon2 = priority_box.itemIcon(priority_box.findText('Major'))
        icon3 = priority_box.itemIcon(priority_box.findText('Critical'))
        icon4 = priority_box.itemIcon(priority_box.findText('Blocker'))
        priority_box.clear()
        priority_box.addItem(icon1, 'Trivial')
        priority_box.addItem(icon0, 'Minor')
        priority_box.addItem(icon2, 'Major')
        priority_box.addItem(icon3, 'Critical')
        priority_box.addItem(icon4, 'Blocker')

        # set more info in tool tip
        major_tip = 'Major: Very important, but workaround available'
        critical_tip = 'Critical: Needs immediate attention, user cant work'
        blocker_tip = 'Blocker: -- SHOW STOPPER -- Entire show cannot work!'
        main_tip = 'The importance of the issue in relation to other issues.'
        tool_tip = '{0}\n\n{1}\n{2}\n{3}\n'.format(main_tip, major_tip, critical_tip, blocker_tip)
        priority_box.setToolTip(tool_tip)
        priority_box.setCurrentIndex(1)

        # make sure pop up menu is turned off for the menu
        priority_box.setStyleSheet("QComboBox { combobox-popup: 0; }")

    def post_edit_type_box(self):
        """Change look of combo box."""
        type_box = self.uiTypeComboBox
        type_box.setStyleSheet("QComboBox { combobox-popup: 0; }")

    def post_create_main_label(self):
        """Add main label."""
        main_label = QtGui.QLabel(self)
        main_label.resize(300, 30)
        main_label.setText('JIRA Submitter')
        main_label.setIndent(50)
        main_label.setStyleSheet("QLabel { color: white; }")
        font = QtGui.QFont()
        font.setFamily("Helvetica [Cronyx]")
        font.setBold(True)
        main_label.setFont(font)

    def post_override_description_text_edit(self):
        """Override the description text color.

        Base class ui uses black text by default in description edit window, this changes it to white.
        """
        # redefine uiDescriptionTextEdit widget created by base class, then create a new one
        self.uiDescriptionLayout.removeWidget(self.uiDescriptionTextEdit)
        self.uiDescriptionTextEdit.setParent(None)

        # redefine widget using our custom Text Edit
        self.uiDescriptionTextEdit = QtGui.QTextEdit()
        self.uiDescriptionTextEdit.setText(self._ticket.comment)

        # reset widget comment and add widget
        self.uiDescriptionLayout.addWidget(self.uiDescriptionTextEdit)

    def post_fix_watchers_line_edit(self):
        """For Houdini, we need a simplified version of this line edit object; causes slowness."""
        # remove uiWatchersLineEdit widget created by base class
        self.uiWatchersLayout.removeWidget(self.uiWatchersLineEdit)
        self.uiWatchersLineEdit.setParent(None)

        # Set the watcher label to blank
        self.uiWatchersLabel.setText("")

    def post_fix_summary_line_edit(self):
        """For Houdini, we need a simplified version of this line edit object; causes slowness."""
        # remove uiSummaryLineEdit widget created by base class, then create a new one
        self.uiSummaryLayout.removeWidget(self.uiSummaryLineEdit)
        self.uiSummaryLineEdit.setParent(None)

        # redefine widget w/o making a connection
        self.uiSummaryLineEdit = QtGui.QLineEdit()
        self.uiSummaryLineEdit.setText(self._ticket.title)

        # add widget back
        self.uiSummaryLayout.addWidget(self.uiSummaryLineEdit)

