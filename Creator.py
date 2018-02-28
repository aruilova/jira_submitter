"""Module contains initialization and interface functions between houdini and ticket dialog."""

# standard Python modules
import re
import os
import Queue
import threading
import tempfile
from time import sleep

# SESI supplied modules
import hou
from qtswitch import QtCore

# local modules
from .HoudiniTicket import *
from .HouJiraReportDialog import *


# post fix to use for temp node to store shelf tool/parent names
DN_TMP_NODE_SHELF_PARENT_POSTFIX = "hou_jira_submit_shelf"

# set sleep interval for submission message detection thread (seconds)
DN_JIRA_SUBMIT_PANE_SLEEP_INC = 2.0

# set sleep max for submission message detection thread (seconds)
DN_JIRA_SUBMIT_PANE_SLEEP_MAX = 7200.0


# ----------------------------------------------------
# functions defined for this module
# ----------------------------------------------------


# open a new HoudiniTicket window here with a reference to this pane_tab object


def create_interface(pane_tab):
    """Run submitter creation functions.

    Since shelf tools cannot pass names to the pane_tab through kwargs, a temp node is created with the shelf tool
    names and is then selected by 'tool_menu_handler' for the sole purpose of passing the names to the pane_tab.

    Args:
        pane_tab (object): pane tab object to attach submitter ui to.

    Returns:
        object: dialog object to pass to parent panel, None if failed

    """
    # Create Ticket and Dialog for first selected node
    sel_nodes = hou.selectedNodes()

    # set tmp shelf tool name regex
    line = re.compile(r"(?P<node>\w+)-(?P<parent>\w+)-{0}.*$".format(DN_TMP_NODE_SHELF_PARENT_POSTFIX))
    num_sel_nodes = len(sel_nodes)
    if num_sel_nodes > 0:

        # check for shelf tmp name
        m = line.search(sel_nodes[0].path())
        if not m:
            jira_submit = HoudiniTicket(item=sel_nodes[0], pane_tab=pane_tab)
            dialog = HouJiraReportDialog(**jira_submit.info_for_dialog)

            # parent new dialog to main window if in houdini 16 and up
            # NOTE: can't do this in houdini 15 and below because in 15 dialog is a PyQt4.QtGui.QWidget whereas parent
            # hou.ui.mainQtWindow() is a PySide.QtGui.QWidget
            if int(hou.applicationVersionString().split(".")[0]) >= 16:
                dialog.setParent(hou.qt.mainWindow(), QtCore.Qt.Window)

            return dialog

        # matches shelf tool regex so treat as shelf tool jira
        elif m.group("node") and m.group("parent"):

            # set shelf names
            owner_name = m.group("node")
            owner_parent_name = None if m.group("parent") == "NONE" else m.group("parent")

            # open a new HoudiniTicket window here with a reference to this pane_tab object
            tool_shelf = None
            if owner_name in hou.shelves.tools():
                tool = hou.shelves.tools()[owner_name]
                if owner_parent_name in hou.shelves.shelves():
                    tool_shelf = hou.shelves.shelves()[owner_parent_name]
                jira_submit = HoudiniTicket(item=tool, item_parent=tool_shelf, pane_tab=pane_tab)
                dialog = HouJiraReportDialog(**jira_submit.info_for_dialog)

                # parent new dialog to main window if in houdini 16 and up
                # NOTE: can't do this in houdini 15 and below because in 15 dialog is a PyQt4.QtGui.QWidget whereas
                # parent hou.ui.mainQtWindow() is a PySide.QtGui.QWidget
                if int(hou.applicationVersionString().split(".")[0]) >= 16:
                    dialog.setParent(hou.qt.mainWindow(), QtCore.Qt.Window)

                # try to remove temp node
                try:
                    # owner_name and owner_parent_name passed to panel through this temp node
                    sel_nodes[0].destroy()
                except (hou.OperationFailed, hou.ObjectWasDeleted):
                    # just leave it
                    pass

                return dialog
            else:
                print "CreateToolInterface: could not find named tool as valid shelf tool: {0}".format(owner_name)
                hou.ui.displayMessage("Something has gone wrong, please check the shell")
    # generic case
    else:
        jira_submit = HoudiniTicket(item=None, pane_tab=pane_tab)
        dialog = HouJiraReportDialog(**jira_submit.info_for_dialog)

        # parent new dialog to main window if in houdini 16 and up
        # NOTE: can't do this in houdini 15 and below because in 15 dialog is a PyQt4.QtGui.QWidget whereas parent
        # hou.ui.mainQtWindow() is a PySide.QtGui.QWidget
        if int(hou.applicationVersionString().split(".")[0]) >= 16:
                dialog.setParent(hou.qt.mainWindow(), QtCore.Qt.Window)

        return dialog


def check_shelf_tool_owner_name(**kwargs):
    """Check kwargs for state of shelf tool names.

    Writes name of tool and name of parent shelf to tmp files, since they cannot be passed to python panel via kwargs.
    The tmp files are then used by creator to pass to HoudiniTicket object.

    Args:
        **kwargs: Arbitrary keyword arguments
        kwargs["ownername"] (str): name of shelf tool

    Raises:
        hou.OperationFailed: Could not valid owner name as valid shelf tool

    """
    if "ownername" not in kwargs or kwargs["ownername"] not in hou.shelves.tools():
        # maybe not called on a Shelf?
        tools = "\n".join(_.name() for _ in hou.shelves.tools())
        raise hou.OperationFailed("{0}.{1} Error: Could not find \"ownername\" in list of available tools. "
                                  "For debugging, kwargs is: {2}\n. Available tools are: {3}".
                                  format(__file__, __name__, str(kwargs), tools))


def tool_menu_handler(**kwargs):
    """Call from ShelfMenu.xml and ShelfToolMenu.xml to handle RMB events on shelves.

    Since shelf tools cannot pass names to the pane_tab through kwargs, a temp node is created with the shelf tool
    names and is then selected by 'tool_menu_handler' for the sole purpose of passing the names to the pane_tab.

    Args:
        **kwargs: Arbitrary keyword arguments passed from houdini
        kwargs["ownername"] (str): name of shelf tool
        kwargs["ownerparentname"] (str): name of shelf tool parent

    Raises:
        hou.OperationFailed: could not create or destroy panel or tmp node.

    """
    # get shelf name and get tool object
    try:
        check_shelf_tool_owner_name(**kwargs)
    except hou.OperationFailed as e:
        hou.ui.displayMessage(str(e))
        raise

    # owner name is ok, so continue
    owner_name = kwargs["ownername"]
    owner_parent_name = kwargs["ownerparentname"] if "owner_parent_name" in kwargs else "NONE"
    tool = hou.shelves.tools()[owner_name]

    try:
        tmp_node = None
        tmp_node_name = ''
        if tool and '.shelf' in tool.filePath():

            # pass owner_name and owner_parent_name to panel through temp node
            tmp_node_name = "{0}-{1}-{2}".format(owner_name, owner_parent_name, DN_TMP_NODE_SHELF_PARENT_POSTFIX)
            tmp_node = hou.node("/obj").createNode("null", node_name=tmp_node_name)

        # handle case where shelf tool is not in hou file path (then launch panel)
        elif tool and '/tools/' not in tool.filePath():
            # might be in an OTL, no direct way to get the OTL file path :(
            # you need to hope that the tool name is identical to the OTL's main type name
            tmp_node_name = "{0}_FOR_JIRA_SUBMISSION_delete_me".format(owner_name)
            tmp_node = hou.node("/obj").createNode(owner_name, node_name=tmp_node_name)

        # launch submitter panel
        if tmp_node and tmp_node_name:
            launch_jira_submit_panel(item=tmp_node)
        else:
            raise hou.OperationFailed("Could not create node: {0}".format(tmp_node_name))

    except hou.OperationFailed as e:
        msg = "This currently only works for DNeg tools in a /tools/* directory\n"
        msg += "or an OTL defined tool where the OTL name is identical\n"
        msg += "to the tool name.\n"
        msg += "\nFor debugging purposes, the exception caught is:\n"
        msg += "\n{0}\n".format(str(e))
        hou.ui.displayMessage(msg)
        raise


def test_is_dneg_tool(node_path):
    """Function to take path to a node and test if it's a Dneg tool.

    Designed to be called by OPmenu expression hence the printing of the 1 or 0.

    Naive assumption that Dneg tools are defined from a path with "/tools/"  or "/builds/" in it. Putting in variable so
    at least if this changes it can be changed once.

    Args:
        node_path (str): path to node to test

    Returns:
        bool: The return value. False if not dneg tool. True if dneg tool.
        0 if not dneg tool, 1 if dneg tool

    """
    # get node for path
    test_dneg_path_prefix = ["/tools/", "/builds/"]
    test_node = hou.node(node_path)
    if not test_node:
        return False
    test_node_type = test_node.type()

    # check for OTL definition
    try:
        definition_path = test_node_type.definition().libraryFilePath()
        if definition_path:
            for test_string in test_dneg_path_prefix:
                if test_string in definition_path:
                    return True

    except AttributeError:
        # not an HDA, carry on
        pass

    # if it's HDK or BOB it should show up here
    dneg_tool = 0
    for test_string in test_dneg_path_prefix:
        if test_string in test_node_type.sourcePath():
            dneg_tool = True
            break

    return dneg_tool


def launch_jira_submit_panel(item=None):
    """RMB on houdini node or tool runs 'submitJiraTicket.hsc' which calls this function.

    Args:
        item (hou.Node or hou.Tool or hou.Shelf): node or tool to open a ticket for, to be passed to panel script.

    Returns:
        hou.Node: Reference to pane_tab object.

    """
    if isinstance(item, hou.Node):
        # select only the node which is passed to the panel launcher
        for _node in hou.selectedNodes():
            _node.setSelected(False)
        item.setSelected(True)

    # Open a floating parameter pane for a particular node
    desktop = hou.ui.curDesktop()
    pane_tab = desktop.createFloatingPaneTab(hou.paneTabType.PythonPanel, size=(700, 600))
    pane_tab.setName('JiraSubmitter')
    jira_submit_panel = hou.pypanel.interfaces()['JiraSubmitter']
    pane_tab.setActiveInterface(jira_submit_panel)
    pane_tab.setPin(False)

    # Launch 'wait_jira_submit' thread that listens for the jira dialog issue creator.
    # Message is passed via a file having the same name as pane tab.
    # This prevents panel object from loosing connection to dialog, houdini crashes otherwise.
    queue = Queue.Queue
    thread = threading.Thread(target=wait_jira_submit, args=(queue, pane_tab))
    thread.daemon = True
    thread.start()

    return pane_tab


def wait_jira_submit(queue, pane_tab):
    """Run child thread that sleeps until it detects the presence of message file.

    The message file is created by the dialog after the job is created to let houdini know it is ok to kill the pane_tab
    Trying to kill the parent pane tab from the dialog child process causes a seg fault in houdini.

    Message file is identified using pane tab name.
    TODO: Investigate replacing this with python event loop callback
    http://127.0.0.1:48628/hom/hou/ui#addEventLoopCallback

    Args:
        pane_tab (hou.PaneTab): active pane tab window
        queue (Queue): if queue object is invalid our parent thread might not run and closing pane might crash houdini

    """
    def find_and_remove_tmp_file(pane_tab_name):
        """Utility function to find and remove temporary message file.

        Args:
            pane_tab_name (str): pane tab name to look for

        """
        # loop over tmp dir looking for file tempfile.tempdir
        tmp_file_suffix = "_hou_jira_submit_pane_tab_{0}_{1}".format(pane_tab_name, hou.hipFile.basename())
        for _file in os.listdir(tempfile.tempdir):
            if _file.endswith(tmp_file_suffix):
                os.remove(_file)
                return True
        return False

    message = "JIRA submission UI has been open for {0} seconds..\nDo you wish to continue?". \
        format(DN_JIRA_SUBMIT_PANE_SLEEP_MAX)

    sleep_time = 0.0
    _pane_tab = pane_tab
    _time_max = DN_JIRA_SUBMIT_PANE_SLEEP_MAX
    if _pane_tab:
        name = _pane_tab.name()
        # sleep for <time> intervals until message file is detected or time limit reached
        while not find_and_remove_tmp_file(name) and _pane_tab:
            sleep(DN_JIRA_SUBMIT_PANE_SLEEP_INC)
            sleep_time += DN_JIRA_SUBMIT_PANE_SLEEP_INC

            # make sure pane tab is still there and update status line
            hou.ui.setStatusMessage("....{0}: waiting for jira ticket creation...".format(__name__),
                                    severity=hou.severityType.ImportantMessage)
            _pane_tab = hou.ui.findPaneTab(name)

            # let user know window has been open for a long time
            if sleep_time > _time_max:
                if hou.ui.displayMessage(message, buttons=("Yes", "No")) == 0:
                    sleep_time = 0.0
                    _pane_tab = hou.ui.findPaneTab(name)
                else:
                    break

        # close pane tab
        kill_pane_tab(queue, _pane_tab)

        # clear status message
        hou.ui.setStatusMessage("")
