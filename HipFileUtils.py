"""Module containing functions for saving the hip file."""

# standard Python modules
import datetime
import os
import subprocess
import time
import re
import string
import random

# dn
import dnsitedata

# SESI supplied modules
import hou


#    site hip file transfer mappings, { 'source site': 'destination sites' }
#    i.e. 'mum': 'lon, van'
#    "if site for source hip file is mumbai, then copy to london and vancouver"

DN_TRANSFER_MAP = {'vancouver': 'london,',
                   'mumbai': 'london,vancouver',
                   'london': 'vancouver,'}

# remote host names
DN_REMOTE_HOST_MAP = {'london': 'nomachine2',
                      'vancouver': 'vannomachine2',
                      'mumbai': 'mumnomachine2'}


def create_timestamped_hip_path(path):
    """Create new hip name to include a date stamp.

    Args:
        path (str): current hip file path.

    Returns:
        String: The full path to the new .hip file.

    """
    # get output file path
    cur_file_name = hou.hipFile.basename().strip(".hip")
    cur_file_dir = os.path.join(os.sep, os.path.dirname(path), "jira")

    # make a timestamp to add to it
    timestamp = time.time()
    date_stamp_string = datetime.datetime.fromtimestamp(timestamp).strftime('%Y_%m_%d_%H_%M_%S')

    # build new name and return path
    new_file_name = "{0}_{1}.hip".format(cur_file_name, date_stamp_string)
    return os.path.join(os.sep, cur_file_dir, new_file_name)


def transfer_hip(new_file_path):
    """Transfer hip file to other sites.

    Args:
        new_file_path (str): current input full path to file

    """
    # get my current site
    site_name = dnsitedata.local_site().name

    # loop over destinations and run rsync
    if site_name in DN_TRANSFER_MAP:
        for dest_site in DN_TRANSFER_MAP[site_name].split(','):
            # rsync: letting failed calls just pass thru silently
            if dest_site:
                rsync_hip_file(dest_site.strip(), new_file_path)


def rsync_hip_file(dest_site, path_to_file):
    """Run rsync command to copy file to remote site.

    Args:
        dest_site (str): output destination site host name.
        path_to_file (str): destination path for file.

    Raises:
        hou.OperationFailed: rsync command itself returned an error.
        subprocess.CalledProcessError: couldnt reach the remote site before even running rsync (fail silently).

    """
    # get proper destination host name
    if dest_site in DN_REMOTE_HOST_MAP:
        host_name = DN_REMOTE_HOST_MAP[dest_site]
    else:
        return

    # run rsync
    user = os.environ["USER"]
    dest_host = '{0}@{1}'.format(user, host_name)
    dest_dir = os.path.dirname(path_to_file)

    try:
        # first, make output dir (fail silently)
        subprocess.Popen(["ssh", dest_host, "mkdir -p {0}".format(dest_dir)])
        dest_dir = '{0}:{1}'.format(dest_host, dest_dir)

        # run rsync command (fail silently)
        sync_paths = "{0} {1}".format(path_to_file, dest_dir)
        rsync_command = "rsync --progress -avvux -ii --keep-dirlinks {0}".format(sync_paths)
        print "\n{0}: Running rsync of backup hip file to remote site:\n\t{1}\n".format(__name__, rsync_command)
        ret = hou.hscript("{0} {1}".format("unix", rsync_command))
        if ret[0]:
            raise hou.OperationFailed("rsync returned error: {0}".format(ret))

    except subprocess.CalledProcessError:
        pass


def print_message(message, is_ui=True):
    """Print a message to user.

    Args:
        message (str): message to print
        is_ui (bool): if we are in UI mode
    """
    if is_ui:
        hou.ui.setStatusMessage(message)
    else:
        print message


def validate_hip_path_or_force_save(orig_path, is_ui=True):
    """Check if the hip file name is 'untitled' or resides non show/shot standard job path, if so, forces user to save
    current hip file using 'DN Save As' before continuing.

    Args:
        orig_path (str): current file path
        is_ui (bool): lets us know if we can put up message windows.

    Returns:
        new_path (str): valid file path

    """

    def random_id(rand_len=5):
        """Create a random id value.
        Args:
            rand_len (int): length of id string to generate

        Returns:
            random id (str): random string

        """
        return ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(rand_len))

    def force_save():
        """Force the user to save the hip file properly before saving a submission copy.

        If not in UI mode, user is not given the choice and the name is force set to 'tmp_save_for_jira.hip'.

        """
        # default save location if it cant be resolved
        random_hip_name = "tmp_save_for_jira_{0}.hip".format(random_id(5))
        default_jira_hip_name = os.path.join(os.sep, "jobs", os.environ["SHOW"], os.environ["SHOT"], "houdini", "hip",
                                             os.environ["USER"], random_hip_name)
        new_file = default_jira_hip_name

        # print message window for option
        if is_ui:
            message = "You need to save this file first before submission\n"
            message += "if you want to use the SAVE COPY OF HIP FILE... option.\n\n"
            message += "Do you want to save this file now?"
            response = hou.ui.displayMessage(message, buttons=('Save', 'Do Not Save'),
                                             severity=hou.severityType.ImportantMessage, default_choice=1,
                                             close_choice=1, title="Should I Save or Should I go?")

            # if saving (response=0) get new hip file name from ui and test for over write
            if not response:
                new_file = hou.ui.selectFile(start_directory=hou.hipFile.path(), title='DN Save As...',
                                             collapse_sequences=False, file_type=hou.fileType.Hip,
                                             pattern="*.hip").strip()

                # fix new file name
                new_file = default_jira_hip_name if not new_file else os.path.expandvars(new_file)
                new_file = "{0}.hip".format(new_file) if ".hip" not in new_file else new_file

                # if new_file already exists query user to over write it, if not use default name
                if os.path.exists(new_file) and \
                        hou.ui.displayMessage('Overwrite Existing File {0}"?'.format(os.path.basename(new_file)),
                                              buttons=('Yes', 'No'),
                                              severity=hou.severityType.ImportantMessage,
                                              default_choice=1):
                    new_file = default_jira_hip_name

        # check if dir is writeable, if not, use default name
        # then save
        if not os.access(os.path.dirname(new_file), os.W_OK):
            new_file = default_jira_hip_name
        try:
            hou.hipFile.save(new_file)
            print_message("File {0} Successfully Saved!".format(new_file), is_ui)
        except hou.OperationFailed:
            # if we still could not save the file at this point, just save to '/u/<username>/tmp_save_for_jira.hip'
            new_file = os.path.join(os.sep, "u", os.environ["USER"], "tmp_save_for_jira.hip")
            hou.hipFile.save(new_file)
            print_message("File {0} Successfully Saved!".format(new_file), is_ui)

        return new_file

    # if path is not valid, do a force save and use new path
    valid_path = orig_path
    valid_base = os.path.join(os.sep, os.environ["SHOW"], os.environ["SHOT"], "houdini", "hip", os.environ["USER"])
    if valid_base not in os.path.dirname(valid_path) or "untitled" in hou.hipFile.basename().strip(".hip"):
        valid_path = force_save()

    return valid_path


def save_hip():
    """Save backup hip file for JIRA reporting.

    Raises:
        hou.OperationFailed: if anything goes wrong with saving to new name, just reset it and return.

    Return:
        tuple (bool, str): (True if the new file path name saved successfully, new path name)

    """
    success = True
    is_ui = hou.isUIAvailable()
    save_file_path = ''

    # ensure current hip file has been saved and is not 'untitled'
    valid_path = validate_hip_path_or_force_save(hou.hipFile.path(), is_ui)

    # create jira dir
    valid_dir = os.path.join(os.sep, os.path.dirname(valid_path), "jira")
    valid_dir = re.sub(r"/hosts/\w+/user_data", '/jobs', valid_dir)
    if not os.path.exists(valid_dir):
        os.makedirs(valid_dir)

    # save renamed file
    try:
        save_file_path = create_timestamped_hip_path(valid_path)
        save_file_path = os.path.join(os.sep, valid_dir, os.path.basename(save_file_path))
        print_message("Saving {0}".format(save_file_path), is_ui)
        hou.hipFile.save(save_file_path)
    except hou.OperationFailed:
        success = False
    else:
        print_message("{0} Saved backup Successfully".format(valid_path), is_ui)
    finally:
        # set name back to original valid_path
        hou.hipFile.setName(valid_path)

    return success, save_file_path


def kill_pane_tab(queue, pane_tab):
    """Kill the pane tab. Also remove any temp files.

    Args:
        pane_tab (hou.PaneTab): pane tab window to close
        queue (Queue): if queue object is invalid our parent thread might not run and closing pane might crash houdini

    Raises:
        OSError: An error occurred with trying to remove tmp files (ignore silently)

    """
    if not queue:
        message = "closing pane tab might be dangerous since operation is not threaded properly, houdini might crash"
        raise hou.OperationFailed(message)

    # get pane tab
    _pane_tab = pane_tab

    # close pane tab
    if _pane_tab:
        _pane_tab.setIsCurrentTab()
        _pane_tab.close()

