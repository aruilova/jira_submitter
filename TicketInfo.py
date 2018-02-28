"""Module containing functions to gather info for the Jira Submitter."""

# standard Python modules
import os

# dn
import dnsitedata

# SESI supplied modules
import hou


# only available inside BOB worlds
try:
    import bobhelper
except ImportError:
    raise ImportError('Not in bob world')


# functions fill auto_info namedtuple


def get_shot_info():
    """Retrieve info about shot from environ."""
    if "SHOT" in os.environ:
        return 'SHOT submitted from: {0}\n'.format(os.environ["SHOT"])
    return 'No SHOT set for this submission\n'


def get_location_info():
    """Retrieve info about shot from dnsitedata."""
    # add section 'location'
    site_name = dnsitedata.local_site().name
    if site_name:
        return 'LOCATION:   {0} \n'.format(site_name.capitalize())
    return 'LOCATION:   Could not find dn_site name\n'


def get_curtools_info():
    """Get curtools, build a list first so it can be sorted."""
    # Gather tool info from env
    raw_hou_env_vars = []
    curtools = "Current DN HOUDINI Tools versions:\n\n"
    for key in os.environ.keys():
        if "HOUDINI" in key and "DN" in key:
            raw_hou_env_vars.append(key)
    raw_hou_env_vars.sort()

    # format env info into strings
    for key in raw_hou_env_vars:
        curtools += "{0}        {1}\n".format(key, os.environ[key])
    return curtools


def get_houdini_version_info():
    """Get houdini version."""
    # get houdini version info
    app_name = "Escape license" if hou.applicationName() == "hescape" else "Master license"
    houdini_version = "Houdini version info:\n\n{0}\n{1}\n{2}\n{3}\n". format(hou.applicationVersionString(),
                                                                              hou.applicationPlatformInfo(),
                                                                              hou.applicationCompilationDate(),
                                                                              app_name)
    houdini_version += "{0}\n".format(os.environ['HFS'])
    return houdini_version


def get_bob_info():
    """Just add bob paths."""
    # noinspection PyBroadException
    try:
        bpath = "BOB Paths and Versions: \n\n"
        bob_world = bobhelper.World()

        # loop thru bob package paths
        for package in sorted(bob_world.packages):
            pack = bob_world.packages[package]
            bpath += '{0}      {1}\n'.format(pack, pack.version)
        return bpath
    except:
        return ''


def get_item_info(issue_type, item, item_parent):
    """Get name information for node.

    Args:
        issue_type (str): whether item is 'node', 'tool', or 'generic'
        item (hou.Node): item node to process
        item (hou.Tool): item tool to process
        item_parent (hou.Shelf): item parent (shelf) to process

    Returns:
        str: required info

    """
    if issue_type == 'dneg_node':
        return "Issue submitted on node: {0}".format(item.path())
    elif issue_type == 'dneg_tool' and isinstance(item_parent, hou.Shelf):
        return "Shelf type: {0}\nShelf name: {1}\nShelf path: {2}".format(item_parent.name(),
                                                                          item_parent.label(),
                                                                          item_parent.filePath())
    elif issue_type == 'dneg_tool':
        return "Tool type: {0}\nTool label: {1}\nTool path: {2}".format(item.name(), item.label(), item.filePath())
    elif issue_type == 'generic':
        return "N/A"
    return ''


def get_item_path_info(issue_type, item):
    """Get path information for node.

    Args:
        issue_type (str): whether item is 'node', 'tool', or 'generic'
        item (hou.Node): item node to precess
        item (hou.Tool): item tool to process

    Raises:
        AttributeError: node definition path doesnt exist, so maybe it's a built in node.
        hou.AttributeError: source path could not be retrieved either (unlikely).

    Returns:
        str: required info

    """
    if issue_type == 'dneg_node':
        item_def = item.type().definition()
        try:
            return "Operator definition path: {0}\n".format(item_def.libraryFilePath())
        except AttributeError:
            try:
                # if not, assume a built in node
                return "Operator definition path: {0}\n".format(item.type().sourcePath())
            except hou.AttributeError:
                # give up
                return "Could not determine source path of node, perhaps a Houdini built in?"
    elif issue_type == 'dneg_tool':
        return "Tool definition path: {0}\n".format(item.filePath())
    elif issue_type == 'generic':
        return "N/A"
    return ''


def get_item_type_info(issue_type, item):
    """Get type information for node.

    Args:
        issue_type (str): whether item is 'node', 'tool', or 'generic'
        item (hou.Node): item node to process
        item (hou.Tool): item tool to process

    Returns:
        str: required info

    """
    if issue_type == 'dneg_node':
        return "Operator type: {0}\n".format(item.type().nameWithCategory())
    elif issue_type == 'dneg_tool':
        return "Tool type: {0}\nTool name: {1}".format(item.name(), item.label())
    elif issue_type == 'generic':
        return "Generic Houdini"
    return ''
