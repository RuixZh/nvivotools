#!/usr/bin/python
# -*- coding: utf-8 -*-

from builtins import chr
from sqlalchemy import *
from sqlalchemy import exc
from xml.dom.minidom import *
import warnings
import sys
import os
import argparse
import uuid
import re
import zlib
from PIL import Image
import StringIO
import tempfile
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.converter import TextConverter
from pdfminer.layout import LAParams
from pdfminer.pdfpage import PDFPage
from cStringIO import StringIO

exec(open(os.path.dirname(os.path.realpath(__file__)) + '/' + 'NVivoTypes.py').read())

try:
    nvivotr = None

    parser = argparse.ArgumentParser(description='Denormalise a normalised NVivo project.')
    parser.add_argument('-w', '--windows', action='store_true',
                        help='Correct NVivo for Windows string coding. Use if offloaded file will be used with Windows version of NVivo.')
    parser.add_argument('-s', '--structure', action='store_true',
                        help='Replace existing table structures.')

    table_choices = ["", "skip", "replace", "merge"]
    parser.add_argument('-p', '--project', choices=table_choices, default="merge",
                        help='Project action.')
    parser.add_argument('-nc', '--node-categories', choices=table_choices, default="merge",
                        help='Node category action.')
    parser.add_argument('-n', '--nodes', choices=table_choices, default="merge",
                        help='Node action.')
    parser.add_argument('-na', '--node-attributes', choices=table_choices, default="merge",
                        help='Node attribute table action.')
    parser.add_argument('-sc', '--source-categories', choices=table_choices, default="merge",
                        help='Source category action.')
    parser.add_argument('--sources', choices=table_choices, default="merge",
                        help='Source action.')
    parser.add_argument('-z', '--compress-level', default='9',
                        help='Compress level for source objects.')
    parser.add_argument('-sa', '--source-attributes', choices=table_choices, default="merge",
                        help='Source attribute action.')
    parser.add_argument('-t', '--taggings', choices=table_choices, default="merge",
                        help='Tagging action.')
    parser.add_argument('-a', '--annotations', choices=table_choices, default="merge",
                        help='Annotation action.')
    parser.add_argument('-u', '--users', choices=table_choices, default="merge",
                        help='User action.')

    parser.add_argument('infile', type=str,
                        help='SQLAlchemy path of input normalised database.')
    parser.add_argument('outfile', type=str, nargs='?',
                        help='SQLAlchemy path of input output NVivo database.')

    args = parser.parse_args()

    normdb = create_engine(args.infile)
    normmd = MetaData(bind=normdb)
    normmd.reflect(normdb)

    if args.outfile is None:
        args.outfile = args.infile.rsplit('.',1)[0] + '.nvivo'
    nvivodb = create_engine(args.outfile, deprecate_large_types=True)
    nvivomd = MetaData(bind=nvivodb)
    nvivomd.reflect(nvivodb)
    nvivocon = nvivodb.connect()
    nvivotr = nvivocon.begin()

    if args.structure:
        nvivomd.drop_all(nvivocon)
        for table in reversed(nvivomd.sorted_tables):
            nvivomd.remove(table)

    nvivoProject = nvivomd.tables.get('Project')
    if nvivoProject == None:
        nvivoProject = Table('Project', nvivomd,
            Column('Title',         String(256),    nullable=False),
            Column('Description',   String(512),    nullable=False),
            Column('CreatedBy',     UUID(),         ForeignKey("UserProfile.Id"),  nullable=False),
            Column('CreatedDate',   DateTime,       nullable=False),
            Column('ModifiedBy',    UUID(),         ForeignKey("UserProfile.Id"),  nullable=False),
            Column('ModifiedDate',  DateTime,       nullable=False))

    nvivoRole = nvivomd.tables.get('Role')
    if nvivoRole == None:
        nvivoRole = Table('Role', nvivomd,
            Column('Item1_Id',      UUID(),         ForeignKey("Item.Id"), primary_key=True, nullable=False),
            Column('TypeId',        Integer,                               primary_key=True, nullable=False),
            Column('Item2_Id',      UUID(),         ForeignKey("Item.Id"), primary_key=True, nullable=False),
            Column('Tag',           Integer))

    nvivoItem = nvivomd.tables.get('Item')
    if nvivoItem == None:
        nvivoItem = Table('Item', nvivomd,
            Column('Id',            UUID(),         primary_key=True, nullable=False),
            Column('TypeId',        Integer,        nullable=False),
            Column('Name',          String(256),    nullable=False),
            Column('Description',   String(512),    nullable=False),
            Column('CreatedDate',   DateTime,       nullable=False),
            Column('ModifiedDate',  DateTime,       nullable=False),
            Column('CreatedBy',     UUID(),         ForeignKey("UserProfile.Id"),  nullable=False),
            Column('ModifiedBy',    UUID(),         ForeignKey("UserProfile.Id"),  nullable=False),
            Column('System',        Boolean,        nullable=False),
            Column('ReadOnly',      Boolean,        nullable=False),
            Column('InheritPermissions', Boolean,   nullable=False),
            Column('ColorArgb',     Integer),
            Column('Aggregate',     Boolean))

    nvivoExtendedItem = nvivomd.tables.get('ExtendedItem')
    if nvivoExtendedItem == None:
        nvivoExtendedItem = Table('ExtendedItem', nvivomd,
            Column('Item_Id',       UUID(),         nullable=False),
            Column('Properties',    LargeBinary,    nullable=False))

    nvivoCategory = nvivomd.tables.get('Category')
    if nvivoCategory == None:
        nvivoCategory = Table('Category', nvivomd,
            Column('Item_Id',       UUID(),         nullable=False),
            Column('Layout',        LargeBinary,    nullable=False))

    nvivoSource = nvivomd.tables.get('Source')
    if nvivoSource == None:
        nvivoSource = Table('Source', nvivomd,
            Column('Item_Id',       UUID(),         nullable=False),
            Column('TypeId',        Integer,        nullable=False),
            Column('Object',        LargeBinary,    nullable=False),
            Column('PlainText',     String),
            Column('MetaData',      String),
            Column('LengthX',       Integer,        nullable=False),
            Column('LengthY',       Integer))

    nvivoNodeReference = nvivomd.tables.get('NodeReference')
    if nvivoNodeReference == None:
        nvivoNodeReference = Table('NodeReference', nvivomd,
            Column('Id',            UUID(),         nullable=False),
            Column('Node_Item_Id',  UUID(),         nullable=False),
            Column('Source_Item_Id', UUID(),        nullable=False),
            Column('CompoundSourceRegion_Id', UUID()),
            Column('ReferenceTypeId', Integer,      nullable=False),
            Column('StartX',        Integer,        nullable=False),
            Column('LengthX',       Integer,        nullable=False),
            Column('StartY',        Integer),
            Column('LengthY',       Integer),
            Column('CreatedDate',   DateTime,       nullable=False),
            Column('ModifiedDate',  DateTime,       nullable=False),
            Column('CreatedBy',     UUID(),         ForeignKey("UserProfile.Id"),  nullable=False),
            Column('ModifiedBy',    UUID(),         ForeignKey("UserProfile.Id"),  nullable=False))

    nvivoAnnotation = nvivomd.tables.get('Annotation')
    if nvivoAnnotation == None:
        nvivoAnnotation = Table('Annotation', nvivomd,
            Column('Id',            UUID(),         primary_key=True, nullable=False),
            Column('Item_Id',       UUID(),         primary_key=True, nullable=False),
            Column('CompoundSourceRegion_Id', UUID()),
            Column('Text',          String(1024), nullable=False),
            Column('ReferenceTypeId', Integer,      nullable=False),
            Column('StartX',        Integer,        nullable=False),
            Column('LengthX',       Integer,        nullable=False),
            Column('StartY',        Integer),
            Column('LengthY',       Integer),
            Column('CreatedDate',   DateTime,       nullable=False),
            Column('ModifiedDate',  DateTime,       nullable=False),
            Column('CreatedBy',     UUID(),         ForeignKey("UserProfile.Id"),  nullable=False),
            Column('ModifiedBy',    UUID(),         ForeignKey("UserProfile.Id"),  nullable=False))

    nvivoUserProfile = nvivomd.tables.get('UserProfile')
    if nvivoUserProfile == None:
        nvivoUserProfile = Table('UserProfile', nvivomd,
            Column('Id',            UUID(),         primary_key=True, nullable=False),
            Column('Initials',      String(16),     nullable=False),
            Column('AccountName',   String(256)),
            Column('ColorArgb',     Integer))

    nvivomd.create_all(nvivocon)

# Users
    if args.users != 'skip':
        print("Denormalising users")
        
        normUser = normmd.tables['User']
        sel = select([normUser.c.Id,
                      normUser.c.Name])

        users = [dict(row) for row in normdb.execute(sel)]
        for user in users:
            user['Initials'] = u''.join(word[0].upper() for word in user['Name'].split())

        userstodelete = nvivocon.execute(select([nvivoUserProfile.c.Id]))
        if args.users == 'replace':
            userstodelete = [dict(row) for row in userstodelete]
        elif args.users == 'merge':
            newusers = [user['Id'] for user in users]
            userstodelete = [dict(row) for row in userstodelete
                             if row['Id'] in newusers]

        if len(userstodelete) > 0:
            nvivocon.execute(nvivoItem.delete(nvivoItem.c.Id == bindparam('Id')), userstodelete)
            
        if len(users) > 0:
            nvivocon.execute(nvivoUserProfile.insert(), users)

# Project
    # First read existing NVivo project record to test that it is there and extract
    # Unassigned and Not Applicable field labels.
    nvivoproject = nvivocon.execute(select([nvivoProject.c.UnassignedLabel,
                                            nvivoProject.c.NotApplicableLabel])).fetchone()
    if nvivoproject == None:
        raise RuntimeError, """
NVivo file contains no project record. Begin denormalisation with an
existing project or stock empty project.
"""
    else:
        unassignedLabel    = nvivoproject['UnassignedLabel']
        notapplicableLabel = nvivoproject['NotApplicableLabel']
        if args.windows:
            unassignedLabel    = u''.join(map(lambda ch: chr(ord(ch) + 0x377), unassignedLabel))
            notapplicableLabel = u''.join(map(lambda ch: chr(ord(ch) + 0x377), notapplicableLabel))

    if args.project != 'skip':
        print("Denormalising project")

        normProject = normmd.tables['Project']
        sel = select([normProject.c.Title,
                      normProject.c.Description,
                      normProject.c.CreatedBy,
                      normProject.c.CreatedDate,
                      normProject.c.ModifiedBy,
                      normProject.c.ModifiedDate])
        projects = [dict(row) for row in normdb.execute(sel)]
        for project in projects:
            if args.windows:
                project['Title']       = u''.join(map(lambda ch: chr(ord(ch) + 0x377), project['Title']))
                project['Description'] = u''.join(map(lambda ch: chr(ord(ch) + 0x377), project['Description']))
                
            nvivocon.execute(nvivoProject.update(), projects)

# Node Categories
    if args.node_categories != 'skip':
        print("Denormalising node categories")

        # Look up head node category, fudge it if it doesn't exist.
        sel = select([nvivoItem.c.Id])
        sel = sel.where(and_(
            nvivoItem.c.TypeId == literal_column('0'),
            nvivoItem.c.Name   == literal_column('\'Node Classifications\''),  # Translate?
            nvivoItem.c.System == True))
        headnodecategory = nvivocon.execute(sel).fetchone()
        if headnodecategory == None:
            #  Create the magic node category from NVivo's empty project
            headnodecategory = {'Id':'987EFFB2-CC02-469B-9BB3-E345BB8F8362'}

        normNodeCategory = normmd.tables['NodeCategory']
        sel = select([normNodeCategory.c.Id,
                      normNodeCategory.c.Name,
                      normNodeCategory.c.Description,
                      normNodeCategory.c.CreatedBy,
                      normNodeCategory.c.CreatedDate,
                      normNodeCategory.c.ModifiedBy,
                      normNodeCategory.c.ModifiedDate])
        nodecategories = [dict(row) for row in normdb.execute(sel)]
        for nodecategory in nodecategories:
            if nodecategory['Id'] == None:
                nodecategory['Id'] = uuid.uuid4()
            if args.windows:
                nodecategory['Name']        = u''.join(map(lambda ch: chr(ord(ch) + 0x377), nodecategory['Name']))
                nodecategory['Description'] = u''.join(map(lambda ch: chr(ord(ch) + 0x377), nodecategory['Description']))

        sel = select([nvivoItem.c.Id,
                      nvivoRole.c.Item1_Id,
                      nvivoRole.c.Item2_Id,
                      nvivoRole.c.TypeId])
        sel = sel.where(and_(
                      nvivoItem.c.TypeId   == literal_column('52'),
                      nvivoRole.c.TypeId   == literal_column('0'),
                      nvivoRole.c.Item2_Id == nvivoItem.c.Id))

        nodecategoriestodelete = nvivocon.execute(sel)
        if args.node_categories == 'replace':
            nodecategoriestodelete = [dict(row) for row in nodecategoriestodelete]
        elif args.node_categories == 'merge':
            newnodecategories = [nodecategory['Id'] for nodecategory in nodecategories]
            nodecategoriestodelete = [dict(row) for row in nodecategoriestodelete
                                      if row['Id'] in newnodecategories]

        if len(nodecategoriestodelete) > 0:
            nvivocon.execute(nvivoItem.delete(
                nvivoItem.c.Id == bindparam('Id')), nodecategoriestodelete)
            nvivocon.execute(nvivoRole.delete(and_(
                nvivoRole.c.Item1_Id == bindparam('Item1_Id'),
                nvivoRole.c.TypeId   == literal_column('0'),
                nvivoRole.c.Item2_Id == bindparam('Item2_Id'))), nodecategoriestodelete)
            nvivocon.execute(nvivoExtendedItem.delete(
                nvivoExtendedItem.c.Item_Id == bindparam('Id')), nodecategoriestodelete)
            nvivocon.execute(nvivoCategory.delete(
                nvivoCategory.c.Item_Id == bindparam('Id')), nodecategoriestodelete)

        if len(nodecategories) > 0:
            nvivocon.execute(nvivoItem.insert().values({
                        'TypeId':   literal_column('52'),
                        'System':   literal_column('0'),
                        'ReadOnly': literal_column('0'),
                        'InheritPermissions': literal_column('1')
                }), nodecategories)

            nvivocon.execute(nvivoRole.insert().values({
                        'Item1_Id': literal_column('\'' + str(headnodecategory['Id']) + '\''),
                        'Item2_Id': bindparam('Id'),
                        'TypeId':   literal_column('0')
                }), nodecategories)
            nvivocon.execute(nvivoExtendedItem.insert().values({
                        'Item_Id': bindparam('Id'),
                        'Properties': literal_column('\'<Properties xmlns="http://qsr.com.au/XMLSchema.xsd"><Property Key="EndNoteReferenceType" Value="-1" /></Properties>\'')
                }), nodecategories)

            # Construct Layout column
            normNode = normmd.tables['Node']
            for nodecategory in nodecategories:
                nodesel = select(
                        [normNode.c.Id]
                                ).where(
                        normNode.c.Category == bindparam('Id')
                                )
                nodes = [dict(row) for row in normdb.execute(nodesel, nodecategory)]
                nodecategory['Layout'] = '<CategoryLayout xmlns="http://qsr.com.au/XMLSchema.xsd">'
                nodeidx = 0
                for node in nodes:
                    nodecategory['Layout'] += '<Row Guid="' + node['Id'] + '" Id="' + str(nodeidx) + '" OrderId="' + str(nodeidx) + '" Hidden="false" Size="-1"/>'
                nodecategory['Layout'] += '<SortedColumn Ascending="true">-1</SortedColumn><RecordHeaderWidth>100</RecordHeaderWidth><ShowRowIDs>true</ShowRowIDs><ShowColumnIDs>true</ShowColumnIDs><Transposed>false</Transposed><NameSource>1</NameSource><RowsUserOrdered>false</RowsUserOrdered><ColumnsUserOrdered>true</ColumnsUserOrdered></CategoryLayout>'

            nvivocon.execute(nvivoCategory.insert().values({
                        'Item_Id': bindparam('Id'),
                        'Layout' : bindparam('Layout')
                }), nodecategories)

#Nodes
    if args.nodes != 'skip':
        print("Denormalising nodes")

        # Look up head node, fudge it if it doesn't exist.
        sel = select([nvivoItem.c.Id])
        sel = sel.where(and_(
            nvivoItem.c.TypeId == literal_column('0'),
            nvivoItem.c.Name == literal_column('\'Nodes\''),
            nvivoItem.c.System == True))
        headnode = nvivocon.execute(sel).fetchone()
        if headnode == None:
            #  Create the magic node from NVivo's empty project
            headnode = {'Id':'F1450EED-D162-4CC9-B45D-6724156F7220'}

        normNode = normmd.tables['Node']
        sel = select([normNode.c.Id,
                      normNode.c.Parent,
                      normNode.c.Category,
                      normNode.c.Name,
                      normNode.c.Description,
                      normNode.c.Color,
                      normNode.c.Aggregate,
                      normNode.c.CreatedBy,
                      normNode.c.CreatedDate,
                      normNode.c.ModifiedBy,
                      normNode.c.ModifiedDate])
        nodes = [dict(row) for row in normdb.execute(sel)]

        tag = 0
        for node in nodes:
            if node['Id'] == None:
                node['Id'] = uuid.uuid4()
            node['PlainTextName'] = node['Name']
            if args.windows:
                node['Name']        = u''.join(map(lambda ch: chr(ord(ch) + 0x377), node['Name']))
                node['Description'] = u''.join(map(lambda ch: chr(ord(ch) + 0x377), node['Description']))

        def tagchildnodes(TopParent, Parent, AggregateList, depth):
            tag = depth << 16
            for node in nodes:
                if node['Parent'] == Parent:
                    node['RoleTag'] = tag
                    tag += 1
                    node['AggregateList'] = [node['Id']] + AggregateList
                    if Parent == None:
                        node['TopParent'] = node['Id']
                    else:
                        node['TopParent'] = TopParent

                    if node['Aggregate']:
                        tagchildnodes(node['TopParent'], node['Id'], node['AggregateList'], depth+1)
                    else:
                        tagchildnodes(node['TopParent'], node['Id'], [], depth+1)

        tagchildnodes(None, None, [], 0)
        aggregatepairs = []
        for node in nodes:
            for dest in node['AggregateList']:
                aggregatepairs += [{ 'Id': node['Id'], 'Ancestor': dest }]

        nodeswithparent   = [dict(row) for row in nodes if row['Parent']   != None]
        nodeswithcategory = [dict(row) for row in nodes if row['Category'] != None]

        sel = select([nvivoItem.c.Id,
                      nvivoRole.c.Item1_Id,
                      nvivoRole.c.Item2_Id,
                      nvivoRole.c.TypeId])
        sel = sel.where(and_(
                        or_(
                            nvivoItem.c.TypeId == literal_column('16'), 
                            nvivoItem.c.TypeId == literal_column('62')),
                        nvivoRole.c.TypeId == literal_column('14'),
                        nvivoRole.c.Item1_Id == nvivoItem.c.Id))

        nodestodelete = nvivocon.execute(sel)
        if args.node_categories == 'replace':
            nodestodelete = [dict(row) for row in nodestodelete]
        elif args.node_categories == 'merge':
            newnodes = [node['Id'] for node in nodes]
            nodestodelete = [dict(row) for row in nodestodelete
                             if row['Id'] in newnodes]

        if len(nodestodelete) > 0:
            nvivocon.execute(nvivoItem.delete(nvivoItem.c.Id == bindparam('Id')), nodestodelete)
            nvivocon.execute(nvivoRole.delete(and_(
                nvivoRole.c.Item1_Id == bindparam('Item1_Id'),
                nvivoRole.c.TypeId   == literal_column('0'),
                nvivoRole.c.Item2_Id == bindparam('Item2_Id'))), nodestodelete)

        if len(nodes) > 0:
            nvivocon.execute(nvivoItem.insert().values({
                    'TypeId':   literal_column('16'),
                    'ColorArgb': bindparam('Color'),
                    'System':   literal_column('0'),
                    'ReadOnly': literal_column('0'),
                    'InheritPermissions': literal_column('1')
                }), nodes)

            nvivocon.execute(nvivoRole.insert().values({
                    'Item1_Id': literal_column('\'' + str(headnode['Id']) + '\''),
                    'Item2_Id': bindparam('Id'),
                    'TypeId':   literal_column('0')
                }), nodes)
            nvivocon.execute(nvivoRole.insert().values({
                    'Item1_Id': bindparam('TopParent'),
                    'Item2_Id': bindparam('Id'),
                    'TypeId':   literal_column('2'),
                    'Tag':      bindparam('RoleTag')
                }), nodes)

        if len(nodeswithcategory) > 0:
            nvivocon.execute(nvivoRole.insert().values({
                    'Item1_Id': bindparam('Id'),
                    'Item2_Id': bindparam('Category'),
                    'TypeId':   literal_column('14')
                }), nodeswithcategory)
        if len(nodeswithparent) > 0:
            nvivocon.execute(nvivoRole.insert().values({
                    'Item1_Id': bindparam('Parent'),
                    'Item2_Id': bindparam('Id'),
                    'TypeId':   literal_column('1')
                }), nodeswithparent)
        if len(aggregatepairs) > 0:
            nvivocon.execute(nvivoRole.insert().values({
                    'Item1_Id': bindparam('Ancestor'),
                    'Item2_Id': bindparam('Id'),
                    'TypeId':   literal_column('15')
                }), aggregatepairs)

# Node attributes
    if args.node_attributes != 'skip':
        print("Denormalising node attributes")

        normNodeAttribute = normmd.tables['NodeAttribute']
        sel = select([normNodeAttribute.c.Node,
                      normNodeAttribute.c.Name,
                      normNodeAttribute.c.Type,
                      normNodeAttribute.c.Value,
                      normNodeAttribute.c.CreatedBy,
                      normNodeAttribute.c.CreatedDate,
                      normNodeAttribute.c.ModifiedBy,
                      normNodeAttribute.c.ModifiedDate])
        nodeattributes = [dict(row) for row in normdb.execute(sel)]

        # The query looks up the node category, then does outer joins to find whether the
        # attribute has already been defined, what its value is, and whether the new value
        # has been defined. It also finds the highest tag for both Category Attributes and
        # Values, as this is needed to create a new attribute or value.
        nvivoNodeCategoryRole  = nvivomd.tables.get('Role').alias(name='NodeCategoryRole')
        nvivoCategoryAttributeRole = nvivomd.tables.get('Role').alias(name='CategoryAttributeRole')
        nvivoCategoryAttributeItem = nvivomd.tables.get('Item').alias(name='CategoryAttributeItem')
        nvivoCategoryAttributeExtendedItem = nvivomd.tables.get('ExtendedItem').alias(name='CategoryAttributeExtendedItem')
        nvivoNewValueRole = nvivomd.tables.get('Role').alias(name='NewValueRole')
        nvivoNewValueItem = nvivomd.tables.get('Item').alias(name='NewValueItem')
        nvivoExistingValueRole = nvivomd.tables.get('Role').alias(name='ExistingValueRole')
        nvivoNodeValueRole = nvivomd.tables.get('Role').alias(name='NodeValueRole')
        nvivoCountAttributeRole = nvivomd.tables.get('Role').alias(name='CountAttributeRole')
        nvivoCountValueRole = nvivomd.tables.get('Role').alias(name='CountValueRole')

        sel = select([
                nvivoNodeCategoryRole.c.Item2_Id.label('CategoryId'),
                nvivoCategoryAttributeItem.c.Id.label('AttributeId'),
                func.CONVERT(literal_column('VARCHAR(MAX)'),nvivoCategoryAttributeExtendedItem.c.Properties),
                nvivoNewValueItem.c.Id.label('NewValueId'),
                nvivoNodeValueRole.c.Item2_Id.label('ExistingValueId'),
                func.max(nvivoCountAttributeRole.c.Tag).label('MaxAttributeTag'),
                func.max(nvivoCountValueRole.c.Tag).label('MaxValueTag')
            ]).where(and_(
                nvivoNodeCategoryRole.c.TypeId   == literal_column('14'),
                nvivoNodeCategoryRole.c.Item1_Id == bindparam('Node')
            )).group_by(nvivoNodeCategoryRole.c.Item2_Id) \
            .group_by(nvivoCategoryAttributeItem.c.Id) \
            .group_by(func.CONVERT(literal_column('VARCHAR(MAX)'),nvivoCategoryAttributeExtendedItem.c.Properties)) \
            .group_by(nvivoNewValueItem.c.Id) \
            .group_by(nvivoNodeValueRole.c.Item2_Id) \
            .select_from(nvivoNodeCategoryRole.outerjoin(
                nvivoCategoryAttributeRole.join(
                        nvivoCategoryAttributeItem.join(
                                nvivoCategoryAttributeExtendedItem,
                                nvivoCategoryAttributeExtendedItem.c.Item_Id == nvivoCategoryAttributeItem.c.Id
                            ), and_(
                        nvivoCategoryAttributeItem.c.Id == nvivoCategoryAttributeRole.c.Item1_Id,
                        nvivoCategoryAttributeItem.c.Name == bindparam('Name')
                )), and_(
                    nvivoCategoryAttributeRole.c.TypeId == literal_column('13'),
                    nvivoCategoryAttributeRole.c.Item2_Id == nvivoNodeCategoryRole.c.Item2_Id
            )).outerjoin(
                nvivoNewValueRole.join(
                    nvivoNewValueItem, and_(
                    nvivoNewValueItem.c.Id == nvivoNewValueRole.c.Item2_Id,
                    nvivoNewValueItem.c.Name == bindparam('Value')
                )), and_(
                    nvivoNewValueRole.c.TypeId == literal_column('6'),
                    nvivoNewValueRole.c.Item1_Id == nvivoCategoryAttributeItem.c.Id
            )).outerjoin(
                nvivoExistingValueRole.join(
                    nvivoNodeValueRole, and_(
                        nvivoNodeValueRole.c.Item2_Id == nvivoExistingValueRole.c.Item2_Id,
                        nvivoNodeValueRole.c.TypeId == literal_column('7'),
                        nvivoNodeValueRole.c.Item1_Id == bindparam('Node')
                    )), and_(
                        nvivoExistingValueRole.c.TypeId == literal_column('6'),
                        nvivoExistingValueRole.c.Item1_Id == nvivoCategoryAttributeItem.c.Id
            )).outerjoin(
                nvivoCountAttributeRole, and_(
                    nvivoCountAttributeRole.c.TypeId == literal_column('13'),
                    nvivoCountAttributeRole.c.Item2_Id == nvivoNodeCategoryRole.c.Item2_Id
            )).outerjoin(
                nvivoCountValueRole, and_(
                    nvivoCountValueRole.c.TypeId == literal_column('6'),
                    nvivoCountValueRole.c.Item1_Id == nvivoCategoryAttributeRole.c.Item1_Id
            ))
            )
                
        addedattributes = []
        for nodeattribute in nodeattributes:
            nodeattribute['NodeName']          = next(node['Name']          for node in nodes if node['Id'] == nodeattribute['Node'])
            nodeattribute['PlainTextNodeName'] = next(node['PlainTextName'] for node in nodes if node['Id'] == nodeattribute['Node'])
            nodeattribute['PlainTextName']     = nodeattribute['Name']
            nodeattribute['PlainTextValue']    = nodeattribute['Value']
            if args.windows:
                nodeattribute['Name']  = u''.join(map(lambda ch: chr(ord(ch) + 0x377), nodeattribute['Name']))
                nodeattribute['Value'] = u''.join(map(lambda ch: chr(ord(ch) + 0x377), nodeattribute['Value']))

            newattributes = [dict(row) for row in nvivocon.execute(sel, nodeattribute)]
            if len(newattributes) == 0:    # Node has no category
                print("WARNING: Node '" + nodeattribute['NodeName'] + "' has no category. NVivo cannot record attributes'")
            else:
                nodeattribute.update(newattributes[0])
                if nodeattribute['Type'] == None:
                    if nodeattribute['Properties'] != None:
                        properties = parseString(nodeattribute['Properties'])
                        for property in properties.documentElement.getElementsByTagName('Property'):
                            if property.getAttribute('Key') == 'DataType':
                                nodeattribute['Type'] = DataTypeName.get(int(property.getAttribute('Value')), property.getAttribute('Value'))
                            elif property.getAttribute('Key') == 'Length':
                                nodeattribute['Length'] = int(property.getAttribute('Value'))
                    else:
                        nodeattribute['Type'] = 'Text'
                    
                if nodeattribute['AttributeId'] == None:
                    print("Creating attribute '" + nodeattribute['PlainTextName'] + "/" + nodeattribute['PlainTextName'] + "' for node '" + nodeattribute['PlainTextNodeName'] + "'")
                    nodeattribute['AttributeId'] = uuid.uuid4()
                    if nodeattribute['MaxAttributeTag'] == None:
                        nodeattribute['NewAttributeTag'] = 0
                    else:
                        nodeattribute['NewAttributeTag'] = nodeattribute['MaxAttributeTag'] + 1
                    nvivocon.execute(nvivoItem.insert().values({
                            'Id':       bindparam('AttributeId'),
                            'Name':     bindparam('Name'),
                            'Description': literal_column('\'\''),
                            'TypeId':   literal_column('20'),
                            'System':   literal_column('0'),
                            'ReadOnly': literal_column('0'),
                            'InheritPermissions': literal_column('1')
                        }), nodeattribute)
                    nvivocon.execute(nvivoRole.insert().values({
                            'Item1_Id': bindparam('AttributeId'),
                            'Item2_Id': bindparam('CategoryId'),
                            'TypeId':   literal_column('13'),
                            'Tag':      bindparam('NewAttributeTag')
                        }), nodeattribute)
                    #print nodeattribute
                    if nodeattribute['Type'] in DataTypeName.values():
                        datatype = DataTypeName.keys()[DataTypeName.values().index(nodeattribute['Type'])]
                    else:
                        datatype = 0;
                    nvivocon.execute(nvivoExtendedItem.insert().values({
                            'Item_Id': bindparam('AttributeId'),
                            'Properties': literal_column('\'<Properties xmlns="http://qsr.com.au/XMLSchema.xsd"><Property Key="DataType" Value="' + str(datatype) + '" /><Property Key="Length" Value="0" /><Property Key="EndNoteFieldTypeId" Value="-1" /></Properties>\'')
                    }), nodeattribute)
                    # Create unassigned and not applicable attribute values
                    nodeattribute['ValueId'] = uuid.uuid4()
                    # Save the attribute and 'Unassigned' value so that it can be filled in for all
                    # nodes of the present category.
                    addedattributes.append({ 'CategoryId':     nodeattribute['CategoryId'],
                                             'AttributeId':    nodeattribute['AttributeId'],
                                             'DefaultValueId': nodeattribute['ValueId'] })
                    nodeattribute['Unassigned'] = unassignedLabel
                    nvivocon.execute(nvivoItem.insert().values({
                            'Id':       bindparam('ValueId'),
                            'Name':     bindparam('Unassigned'),
                            'Description': literal_column('\'\''),
                            'TypeId':   literal_column('21'),
                            'System':   literal_column('1'),
                            'ReadOnly': literal_column('0'),
                            'InheritPermissions': literal_column('1'),
                            'ColorArgb': literal_column('0')
                        }), nodeattribute)
                    nvivocon.execute(nvivoRole.insert().values({
                            'Item1_Id': bindparam('AttributeId'),
                            'Item2_Id': bindparam('ValueId'),
                            'TypeId':   literal_column('6'),
                            'Tag':      literal_column('0')
                        }), nodeattribute )
                    nvivocon.execute(nvivoExtendedItem.insert().values({
                            'Item_Id': bindparam('ValueId'),
                            'Properties': literal_column('\'<Properties xmlns="http://qsr.com.au/XMLSchema.xsd"><Property Key="IsDefault" Value="True"/></Properties>\'')
                    }), nodeattribute)
                    nodeattribute['ValueId'] = uuid.uuid4()
                    nodeattribute['NotApplicable'] = notapplicableLabel
                    nvivocon.execute(nvivoItem.insert().values({
                            'Id':       bindparam('ValueId'),
                            'Name':     bindparam('NotApplicable'),
                            'Description': literal_column('\'\''),
                            'TypeId':   literal_column('21'),
                            'System':   literal_column('1'),
                            'ReadOnly': literal_column('0'),
                            'InheritPermissions': literal_column('1'),
                            'ColorArgb': literal_column('0')
                        }), nodeattribute)
                    nvivocon.execute(nvivoRole.insert().values({
                            'Item1_Id': bindparam('AttributeId'),
                            'Item2_Id': bindparam('ValueId'),
                            'TypeId':   literal_column('6'),
                            'Tag':      literal_column('1')
                        }), nodeattribute )
                    nvivocon.execute(nvivoExtendedItem.insert().values({
                            'Item_Id': bindparam('ValueId'),
                            'Properties': literal_column('\'<Properties xmlns="http://qsr.com.au/XMLSchema.xsd"><Property Key="IsDefault" Value="False"/></Properties>\'')
                    }), nodeattribute)
                    nodeattribute['MaxValueTag'] = 1

                if nodeattribute['NewValueId'] == None:
                    print("Creating value '" + nodeattribute['PlainTextValue'] + "' for attribute '" + nodeattribute['PlainTextName'] + "' for node '" + nodeattribute['PlainTextNodeName'] + "'")
                    nodeattribute['NewValueId']  = uuid.uuid4()
                    nodeattribute['NewValueTag'] = nodeattribute['MaxValueTag'] + 1
                    nvivocon.execute(nvivoItem.insert().values({
                            'Id':       bindparam('NewValueId'),
                            'Name':     bindparam('Value'),
                            'Description': literal_column('\'\''),
                            'TypeId':   literal_column('21'),
                            'System':   literal_column('0'),
                            'ReadOnly': literal_column('0'),
                            'InheritPermissions': literal_column('1')
                        }), nodeattribute )
                    nvivocon.execute(nvivoRole.insert().values({
                            'Item1_Id': bindparam('AttributeId'),
                            'Item2_Id': bindparam('NewValueId'),
                            'TypeId':   literal_column('6'),
                            'Tag':      bindparam('NewValueTag')
                        }), nodeattribute )
                    nvivocon.execute(nvivoExtendedItem.insert().values({
                            'Item_Id': bindparam('NewValueId'),
                            'Properties': literal_column('\'<Properties xmlns="http://qsr.com.au/XMLSchema.xsd"><Property Key="IsDefault" Value="False"/></Properties>\'')
                    }), nodeattribute)

                if nodeattribute['NewValueId'] != nodeattribute['ExistingValueId']:
                    if nodeattribute['ExistingValueId'] != None:
                        print("Removing existing value of attribute '" + nodeattribute['PlainTextName'] + "' for node '" + nodeattribute['PlainTextNodeName'] + "'")
                        nvivocon.execute(nvivoRole.delete().values({
                                'Item1_Id': bindparam('Node'),
                                'Item2_Id': bindparam('ExistingValueId'),
                                'TypeId':   literal_column('7')
                            }), nodeattribute )
                    #print("Assigning value '" + nodeattribute['PlainTextValue'] + "' for attribute '" + nodeattribute['PlainTextName'] + "' for node '" + nodeattribute['PlainTextNodeName'] + "'")
                    nvivocon.execute(nvivoRole.insert().values({
                            'Item1_Id': bindparam('Node'),
                            'Item2_Id': bindparam('NewValueId'),
                            'TypeId':   literal_column('7')
                        }), nodeattribute )

        # Fill in default ('Undefined') value for all nodes lacking an attribute value
        sel = select([
                nvivoNodeCategoryRole.c.Item1_Id.label('NodeId'),
                func.count(nvivoExistingValueRole.c.Item1_Id).label('ValueCount')
            ]).where(and_(
                nvivoNodeCategoryRole.c.TypeId   == literal_column('14'),
                nvivoNodeCategoryRole.c.Item2_Id == bindparam('CategoryId')
            )).group_by(nvivoNodeCategoryRole.c.Item1_Id)\
            .select_from(nvivoNodeCategoryRole.outerjoin(
                nvivoExistingValueRole.join(
                    nvivoNodeValueRole, and_(
                        nvivoNodeValueRole.c.Item2_Id == nvivoExistingValueRole.c.Item2_Id,
                        nvivoNodeValueRole.c.TypeId == literal_column('7')
                    )), and_(
                        nvivoExistingValueRole.c.TypeId == literal_column('6'),
                        nvivoExistingValueRole.c.Item1_Id == bindparam('AttributeId'),
                        nvivoNodeValueRole.c.Item1_Id == nvivoNodeCategoryRole.c.Item1_Id
            )))

        categorysel = select([nvivoCategory.c.Layout]).where(
                              nvivoCategory.c.Item_Id == bindparam('CategoryId'))
        for addedattribute in addedattributes:
            # Patch up Layout column in Category table
            category = dict(nvivocon.execute(categorysel, addedattribute).fetchone())
            layoutdoc = parseString(category['Layout'])
            followingelement = layoutdoc.documentElement.getElementsByTagName('SortedColumn')[0]
            previouselement = followingelement.previousSibling
            if previouselement != None and previouselement.tagName == 'Column':
                nextid = int(previouselement.getAttribute('Id')) + 1
            else:
                nextid = 0
            newelement = layoutdoc.createElement('Column')
            newelement.setAttribute('Guid', str(addedattribute['AttributeId']))
            newelement.setAttribute('Id', str(nextid))
            newelement.setAttribute('OrderId', str(nextid))
            newelement.setAttribute('Hidden', 'false')
            newelement.setAttribute('Size', '-1')
            layoutdoc.documentElement.insertBefore(newelement, followingelement)
            category['Layout'] = layoutdoc.documentElement.toxml()
            nvivocon.execute(nvivoCategory.update(), category)

            # Set value of undefined attribute to 'Unassigned'
            attributes = [dict(row) for row in nvivocon.execute(sel, addedattribute)]
            for attribute in attributes:
                if attribute['ValueCount'] == 0:
                    attribute.update(addedattribute)
                    #print(attribute)
                    nvivocon.execute(nvivoRole.insert().values({
                            'Item1_Id': bindparam('NodeId'),
                            'Item2_Id': bindparam('DefaultValueId'),
                            'TypeId':   literal_column('7')
                        }), attribute )

# Source categories
    if args.source_categories != 'skip':
        print("Denormalising source categories")

        # Look up head source category, fudge it if it doesn't exist.
        sel = select([nvivoItem.c.Id])
        sel = sel.where(and_(
            nvivoItem.c.TypeId == literal_column('0'),
            nvivoItem.c.Name   == literal_column('\'Source Classifications\''),  # Translate?
            nvivoItem.c.System == True))
        headsourcecategory = nvivocon.execute(sel).fetchone()
        if headsourcecategory == None:
            #  Create the magic source category from NVivo's empty project
            headsourcecategory = {'Id':'72218145-56BB-4FFA-A6D5-348F5D4766F1'}

        normSourceCategory = normmd.tables['SourceCategory']
        sel = select([normSourceCategory.c.Id,
                      normSourceCategory.c.Name,
                      normSourceCategory.c.Description,
                      normSourceCategory.c.CreatedBy,
                      normSourceCategory.c.CreatedDate,
                      normSourceCategory.c.ModifiedBy,
                      normSourceCategory.c.ModifiedDate])
        sourcecategories = [dict(row) for row in normdb.execute(sel)]
        for sourcecategory in sourcecategories:
            if sourcecategory['Id'] == None:
                sourcecategory['Id'] = uuid.uuid4()
            if args.windows:
                sourcecategory['Name']        = u''.join(map(lambda ch: chr(ord(ch) + 0x377), sourcecategory['Name']))
                sourcecategory['Description'] = u''.join(map(lambda ch: chr(ord(ch) + 0x377), sourcecategory['Description']))

        sel = select([nvivoItem.c.Id,
                      nvivoRole.c.Item1_Id,
                      nvivoRole.c.Item2_Id,
                      nvivoRole.c.TypeId])
        sel = sel.where(and_(
                      nvivoItem.c.TypeId   == literal_column('51'),
                      nvivoRole.c.TypeId   == literal_column('0'),
                      nvivoRole.c.Item2_Id == nvivoItem.c.Id))

        sourcecategoriestodelete = nvivocon.execute(sel)
        if args.source_categories == 'replace':
            sourcecategoriestodelete = [dict(row) for row in sourcecategoriestodelete]
        elif args.source_categories == 'merge':
            newsourcecategories = [sourcecategory['Id'] for sourcecategory in sourcecategories]
            sourcecategoriestodelete = [dict(row) for row in sourcecategoriestodelete
                                        if row['Id'] in newsourcecategories]

        if len(sourcecategoriestodelete) > 0:
            nvivocon.execute(nvivoItem.delete(
                nvivoItem.c.Id == bindparam('Id')), sourcecategoriestodelete)
            nvivocon.execute(nvivoRole.delete(and_(
                nvivoRole.c.Item1_Id == bindparam('Item1_Id'),
                nvivoRole.c.TypeId   == literal_column('0'),
                nvivoRole.c.Item2_Id == bindparam('Item2_Id'))), sourcecategoriestodelete)
            nvivocon.execute(nvivoExtendedItem.delete(
                nvivoExtendedItem.c.Item_Id == bindparam('Id')), sourcecategoriestodelete)
            nvivocon.execute(nvivoCategory.delete(
                nvivoCategory.c.Item_Id == bindparam('Id')), sourcecategoriestodelete)

        if len(sourcecategories) > 0:
            nvivocon.execute(nvivoItem.insert().values({
                        'TypeId':   literal_column('51'),
                        'System':   literal_column('0'),
                        'ReadOnly': literal_column('0'),
                        'InheritPermissions': literal_column('1')
                }), sourcecategories)

            nvivocon.execute(nvivoRole.insert().values({
                        'Item1_Id': literal_column('\'' + str(headsourcecategory['Id']) + '\''),
                        'Item2_Id': bindparam('Id'),
                        'TypeId':   literal_column('0')
                }), sourcecategories)
            nvivocon.execute(nvivoExtendedItem.insert().values({
                        'Item_Id': bindparam('Id'),
                        'Properties': literal_column('\'<Properties xmlns="http://qsr.com.au/XMLSchema.xsd"><Property Key="EndNoteReferenceType" Value="-1" /></Properties>\'')
                }), sourcecategories)
            nvivocon.execute(nvivoCategory.insert().values({
                        'Item_Id': bindparam('Id'),
                        'Layout' : literal_column('\'<CategoryLayout xmlns="http://qsr.com.au/XMLSchema.xsd"><SortedColumn Ascending="true">-1</SortedColumn><RecordHeaderWidth>100</RecordHeaderWidth><ShowRowIDs>true</ShowRowIDs><ShowColumnIDs>true</ShowColumnIDs><Transposed>false</Transposed><NameSource>1</NameSource><RowsUserOrdered>false</RowsUserOrdered><ColumnsUserOrdered>true</ColumnsUserOrdered></CategoryLayout>\'')
                }), sourcecategories)

# Sources
    if args.sources != 'skip':
        print("Denormalising sources")

        # Look up head source, fudge it if it doesn't exist.
        sel = select([nvivoItem.c.Id])
        sel = sel.where(and_(
            nvivoItem.c.TypeId == literal_column('0'),
            nvivoItem.c.Name == literal_column('\'Internals\''),
            nvivoItem.c.System == True))
        headsource = nvivocon.execute(sel).fetchone()
        if headsource == None:
            #  Create the 'Internals' source from NVivo's empty project
            headsource = {'Id':'89288984-4637-42A8-8999-FCB8334BDA68'}

        normSource = normmd.tables['Source']
        sel = select([normSource.c.Id.label('Item_Id'),
                      normSource.c.Category,
                      normSource.c.Name,
                      normSource.c.Description,
                      normSource.c.Color,
                      normSource.c.Content,
                      normSource.c.ObjectType.label('ObjectTypeName'),
                      #normSource.c.SourceType,
                      normSource.c.Object,
                      normSource.c.Thumbnail,
                      normSource.c.CreatedBy,
                      normSource.c.CreatedDate,
                      normSource.c.ModifiedBy,
                      normSource.c.ModifiedDate])
        sources = [dict(row) for row in normdb.execute(sel)]

        for source in sources:
            
            if source['Item_Id'] == None:
                source['Item_Id'] = uuid.uuid4()
            source['PlainTextName'] = source['Name']
            if args.windows:
                source['Name']        = u''.join(map(lambda ch: chr(ord(ch) + 0x377), source['Name']))
                source['Description'] = u''.join(map(lambda ch: chr(ord(ch) + 0x377), source['Description']))
                
            # Lookup object type from name
            if source['ObjectTypeName'] in ObjectTypeName.values():
                source['ObjectType'] = ObjectTypeName.keys()[ObjectTypeName.values().index(source['ObjectTypeName'])]
            else:
                source['ObjectType'] = int(source['ObjectTypeName'])

            #if source['Content'] != None:
                #source['PlainText'] = source['Content']
            #else:
                #source['PlainText'] = None
                    
            if source['ObjectTypeName'] == 'PDF':
                source['SourceType'] = 34
                source['LengthX'] = 0
                
                doc = Document()
                pages = doc.createElement("PdfPages")
                pages.setAttribute("xmlns", "http://qsr.com.au/XMLSchema.xsd")
                
                tmpfilename = tempfile.mktemp()
                tmpfileptr  = file(tmpfilename, 'wb')
                tmpfileptr.write(source['Object'])
                tmpfileptr.close()
                rsrcmgr = PDFResourceManager()
                retstr = StringIO()
                laparams = LAParams()
                device = TextConverter(rsrcmgr, retstr, codec='utf-8', laparams=laparams)
                tmpfileptr = file(tmpfilename, 'rb')
                interpreter = PDFPageInterpreter(rsrcmgr, device)
                pagenos = set()
                pdfpages = PDFPage.get_pages(tmpfileptr, password='', check_extractable=True)
                pageoffset = 0
                pdfstr = u''
                for pdfpage in pdfpages:
                    mediabox   = pdfpage.attrs['MediaBox']
                    
                    interpreter.process_page(pdfpage)
                    pageelement = pages.appendChild(doc.createElement("PdfPage"))
                    pageelement.setAttribute("PageLength", str(retstr.tell()))
                    pageelement.setAttribute("PageOffset", str(pageoffset))
                    pageelement.setAttribute("PageWidth",  str(int(mediabox[2] - mediabox[0])))
                    pageelement.setAttribute("PageHeight", str(int(mediabox[3] - mediabox[1])))
                    
                    pagestr = unicode(retstr.getvalue().replace('\n\n', '\l').replace('\n', ' ').replace('\l','\n'), 'utf-8')
                    retstr.truncate(0)
                    pdfstr += pagestr
                    pageoffset += len(pagestr)
                                        
                source['PlainText'] = pdfstr
                tmpfileptr.close()
                os.remove(tmpfilename)
                
                paragraphs = doc.createElement("Paragraphs")
                paragraphs.setAttribute("xmlns", "http://qsr.com.au/XMLSchema.xsd")
                start = 0
                while start < len(source['PlainText']):
                    end = source['PlainText'].find('\n', start)
                    if end == -1:
                        end = len(source['PlainText']) - 1
                    para = paragraphs.appendChild(doc.createElement("Para"))
                    para.setAttribute("Pos", str(start))
                    para.setAttribute("Len", str(end - start + 1))
                    para.setAttribute("Style", "")
                    start = end + 1

                source['MetaData'] = paragraphs.toxml() + pages.toxml()
            elif source['ObjectTypeName'] == 'DOC':
                source['LengthX'] = 0
                settings = doc.createElement("DisplaySettings")
                settings.setAttribute("xmlns", "http://qsr.com.au/XMLSchema.xsd")
                settings.setAttribute("InputPosition", "0")
                source['MetaData'] += settings.toxml()
                # Compress object using zlib without header
                if int(args.compress_level) != 0:
                    print ("Compressing with level " + args.compress_level)
                    compressor = zlib.compressobj(int(args.compress_level), zlib.DEFLATED, -15)
                    source['Object'] = compressor.compress(source['Object']) + compressor.flush()
                    
                doc = Document()
                paragraphs = doc.createElement("Paragraphs")
                paragraphs.setAttribute("xmlns", "http://qsr.com.au/XMLSchema.xsd")
                start = 0
                while start < len(source['Content']):
                    end = source['Content'].find('\n', start)
                    if end == -1:
                        end = len(source['Content']) - 1
                    para = paragraphs.appendChild(doc.createElement("Para"))
                    para.setAttribute("Pos", str(start))
                    para.setAttribute("Len", str(end - start + 1))
                    para.setAttribute("Style", "Normal")
                    start = end + 1

                source['MetaData'] = paragraphs.toxml() + pages.toxml()
            elif source['ObjectTypeName'] == 'JPEG':
                image = Image.open(StringIO.StringIO(source['Object']))
                source['LengthX'], source['LengthY'] = image.size
            #elif source['ObjectTypeName'] == 'MP3':
                #source['LengthX'] = length of recording in milliseconds
                #source['Waveform'] = waveform of recording, one byte per centisecond
            #elif source['ObjectTypeName'] == 'WMV':
                #source['LengthX'] = length of recording in milliseconds
                #source['Waveform'] = waveform of recording, one byte per centisecond
            else:
                source['LengthX'] = 0
                    
        sourceswithcategory = [dict(row) for row in sources if row['Category'] != None]

        sourcestodelete = nvivocon.execute(select([nvivoSource.c.Item_Id]))
        if args.source_categories == 'replace':
            sourcestodelete = [dict(row) for row in sourcestodelete]
        elif args.source_categories == 'merge':
            newsources = [source['Item_Id'] for source in sources]
            sourcestodelete = [dict(row) for row in sourcestodelete
                               if row['Item_Id'] in newsources]

        if len(sourcestodelete) > 0:
            # Need to delete taggings associated with source
            nvivocon.execute(nvivoSource.delete(nvivoSource.c.Id == bindparam('Id')), sourcestodelete)
            nvivocon.execute(nvivoItem.delete(nvivoItem.c.Id == bindparam('Id')), sourcestodelete)
            nvivocon.execute(nvivoRole.delete(and_(
                nvivoRole.c.Item1_Id == bindparam('Id'),
                nvivoRole.c.TypeId   == literal_column('14')), sourcestodelete))

        if len(sources) > 0:
            nvivocon.execute(nvivoItem.insert().values({
                    'Id':       bindparam('Item_Id'),
                    'TypeId':   bindparam('SourceType'),
                    'ColorArgb': bindparam('Color'),
                    'System':   literal_column('0'),
                    'ReadOnly': literal_column('0'),
                    'InheritPermissions': literal_column('1')
                }), sources)
            nvivocon.execute(nvivoSource.insert().values({
                    'TypeId':   bindparam('ObjectType'),
                    # This work-around is specific to MSSQL
                    'Object':   func.CONVERT(literal_column('VARBINARY(MAX)'),
                                             bindparam('Object')),
                    'Thumbnail': func.CONVERT(literal_column('VARBINARY(MAX)'),
                                             bindparam('Thumbnail')),
                }), sources)
            nvivocon.execute(nvivoRole.insert().values({
                    'Item1_Id': literal_column('\'' + str(headsource['Id']) + '\''),
                    'Item2_Id': bindparam('Item_Id'),
                    'TypeId':   literal_column('0')
                }), sources)
            if source['ObjectTypeName'] == 'PDF':
                nvivocon.execute(nvivoExtendedItem.insert().values({
                        # Need to work out how to calculate PDF checksum!
                        'Properties': literal_column('\'<Properties xmlns="http://qsr.com.au/XMLSchema.xsd"><Property Key="PDFChecksum" Value="0"/><Property Key="PDFPassword" Value=""/></Properties>\'')
                    }), sources)
            else:
                nvivocon.execute(nvivoExtendedItem.insert().values({
                        'Properties': literal_column('\'<Properties xmlns="http://qsr.com.au/XMLSchema.xsd"/>\'')
                    }), sources)

        if len(sourceswithcategory) > 0:
            nvivocon.execute(nvivoRole.insert().values({
                    'Item1_Id': bindparam('Item_Id'),
                    'Item2_Id': bindparam('Category'),
                    'TypeId':   literal_column('14')
                }), sourceswithcategory)

# Source attributes
    if args.source_attributes != 'skip':
        print("Denormalising source attributes")

        sources = [dict(row) for row in nvivocon.execute(select([nvivoSource.c.Item_Id,
                                                                 nvivoItem.  c.Name]).
                                                         where ( nvivoItem.  c.Id == nvivoSource.c.Item_Id))]

        normSourceAttribute = normmd.tables['SourceAttribute']
        sel = select([normSourceAttribute.c.Source,
                      normSourceAttribute.c.Name,
                      normSourceAttribute.c.Type,
                      normSourceAttribute.c.Value,
                      normSourceAttribute.c.CreatedBy,
                      normSourceAttribute.c.CreatedDate,
                      normSourceAttribute.c.ModifiedBy,
                      normSourceAttribute.c.ModifiedDate])
        sourceattributes = [dict(row) for row in normdb.execute(sel)]

        # The query looks up the source category, then does outer joins to find whether the
        # attribute has already been defined, what its value is, and whether the new value
        # has been defined. It also finds the highest tag for both Category Attributes and
        # Values, as this is needed to create a new attribute or value.
        nvivoSourceCategoryRole  = nvivomd.tables.get('Role').alias(name='SourceCategoryRole')
        nvivoCategoryAttributeRole = nvivomd.tables.get('Role').alias(name='CategoryAttributeRole')
        nvivoCategoryAttributeItem = nvivomd.tables.get('Item').alias(name='CategoryAttributeItem')
        nvivoCategoryAttributeExtendedItem = nvivomd.tables.get('ExtendedItem').alias(name='CategoryAttributeExtendedItem')
        nvivoNewValueRole = nvivomd.tables.get('Role').alias(name='NewValueRole')
        nvivoNewValueItem = nvivomd.tables.get('Item').alias(name='NewValueItem')
        nvivoExistingValueRole = nvivomd.tables.get('Role').alias(name='ExistingValueRole')
        nvivoSourceValueRole = nvivomd.tables.get('Role').alias(name='SourceValueRole')
        nvivoCountAttributeRole = nvivomd.tables.get('Role').alias(name='CountAttributeRole')
        nvivoCountValueRole = nvivomd.tables.get('Role').alias(name='CountValueRole')

        sel = select([
                nvivoSourceCategoryRole.c.Item2_Id.label('CategoryId'),
                nvivoCategoryAttributeItem.c.Id.label('AttributeId'),
                func.CONVERT(literal_column('VARCHAR(MAX)'),nvivoCategoryAttributeExtendedItem.c.Properties),
                nvivoNewValueItem.c.Id.label('NewValueId'),
                nvivoSourceValueRole.c.Item2_Id.label('ExistingValueId'),
                func.max(nvivoCountAttributeRole.c.Tag).label('MaxAttributeTag'),
                func.max(nvivoCountValueRole.c.Tag).label('MaxValueTag')
            ]).where(and_(
                nvivoSourceCategoryRole.c.TypeId   == literal_column('14'),
                nvivoSourceCategoryRole.c.Item1_Id == bindparam('Source')
            )).group_by(nvivoSourceCategoryRole.c.Item2_Id) \
            .group_by(nvivoCategoryAttributeItem.c.Id) \
            .group_by(func.CONVERT(literal_column('VARCHAR(MAX)'),nvivoCategoryAttributeExtendedItem.c.Properties)) \
            .group_by(nvivoNewValueItem.c.Id) \
            .group_by(nvivoSourceValueRole.c.Item2_Id) \
            .select_from(nvivoSourceCategoryRole.outerjoin(
                nvivoCategoryAttributeRole.join(
                        nvivoCategoryAttributeItem.join(
                                nvivoCategoryAttributeExtendedItem,
                                nvivoCategoryAttributeExtendedItem.c.Item_Id == nvivoCategoryAttributeItem.c.Id
                            ), and_(
                        nvivoCategoryAttributeItem.c.Id == nvivoCategoryAttributeRole.c.Item1_Id,
                        nvivoCategoryAttributeItem.c.Name == bindparam('Name')
                )), and_(
                    nvivoCategoryAttributeRole.c.TypeId == literal_column('13'),
                    nvivoCategoryAttributeRole.c.Item2_Id == nvivoSourceCategoryRole.c.Item2_Id
            )).outerjoin(
                nvivoNewValueRole.join(
                    nvivoNewValueItem, and_(
                    nvivoNewValueItem.c.Id == nvivoNewValueRole.c.Item2_Id,
                    nvivoNewValueItem.c.Name == bindparam('Value')
                )), and_(
                    nvivoNewValueRole.c.TypeId == literal_column('6'),
                    nvivoNewValueRole.c.Item1_Id == nvivoCategoryAttributeItem.c.Id
            )).outerjoin(
                nvivoExistingValueRole.join(
                    nvivoSourceValueRole, and_(
                        nvivoSourceValueRole.c.Item2_Id == nvivoExistingValueRole.c.Item2_Id,
                        nvivoSourceValueRole.c.TypeId == literal_column('7'),
                        nvivoSourceValueRole.c.Item1_Id == bindparam('Source')
                    )), and_(
                        nvivoExistingValueRole.c.TypeId == literal_column('6'),
                        nvivoExistingValueRole.c.Item1_Id == nvivoCategoryAttributeItem.c.Id
            )).outerjoin(
                nvivoCountAttributeRole, and_(
                    nvivoCountAttributeRole.c.TypeId == literal_column('13'),
                    nvivoCountAttributeRole.c.Item2_Id == nvivoSourceCategoryRole.c.Item2_Id
            )).outerjoin(
                nvivoCountValueRole, and_(
                    nvivoCountValueRole.c.TypeId == literal_column('6'),
                    nvivoCountValueRole.c.Item1_Id == nvivoCategoryAttributeRole.c.Item1_Id
            ))
            )

        addedattributes = []
        for sourceattribute in sourceattributes:
            sourceattribute['SourceName']          = next(source['Name']          for source in sources if source['Item_Id'] == uuid.UUID(sourceattribute['Source']))
            sourceattribute['PlainTextSourceName'] = sourceattribute['SourceName']
            sourceattribute['PlainTextName']       = sourceattribute['Name']
            sourceattribute['PlainTextValue']      = sourceattribute['Value']
            if args.windows:
                sourceattribute['PlainTextSourceName'] = u''.join(map(lambda ch: chr(ord(ch) - 0x377), sourceattribute['PlainTextSourceName']))
                sourceattribute['Name']  = u''.join(map(lambda ch: chr(ord(ch) + 0x377), sourceattribute['Name']))
                sourceattribute['Value'] = u''.join(map(lambda ch: chr(ord(ch) + 0x377), sourceattribute['Value']))

            newattributes = [dict(row) for row in nvivocon.execute(sel, sourceattribute)]
            if len(newattributes) == 0:    # Source has no category
                print("WARNING: Source '" + sourceattribute['SourceName'] + "' has no category. NVivo cannot record attributes'")
            else:
                sourceattribute.update(newattributes[0])
                if sourceattribute['Type'] == None:
                    if sourceattribute['Properties'] != None:
                        properties = parseString(sourceattribute['Properties'])
                        for property in properties.documentElement.getElementsByTagName('Property'):
                            if property.getAttribute('Key') == 'DataType':
                                sourceattribute['Type'] = DataTypeName.get(int(property.getAttribute('Value')), property.getAttribute('Value'))
                            elif property.getAttribute('Key') == 'Length':
                                sourceattribute['Length'] = int(property.getAttribute('Value'))
                    else:
                        sourceattribute['Type'] = 'Text'
                    
                if sourceattribute['AttributeId'] == None:
                    print("Creating attribute '" + sourceattribute['PlainTextName'] + "' for source '" + sourceattribute['PlainTextSourceName'] + "'")
                    sourceattribute['AttributeId'] = uuid.uuid4()
                    if sourceattribute['MaxAttributeTag'] == None:
                        sourceattribute['NewAttributeTag'] = 0
                    else:
                        sourceattribute['NewAttributeTag'] = sourceattribute['MaxAttributeTag'] + 1
                    nvivocon.execute(nvivoItem.insert().values({
                            'Id':       bindparam('AttributeId'),
                            'Name':     bindparam('Name'),
                            'Description': literal_column('\'\''),
                            'TypeId':   literal_column('20'),
                            'System':   literal_column('0'),
                            'ReadOnly': literal_column('0'),
                            'InheritPermissions': literal_column('1')
                        }), sourceattribute)
                    nvivocon.execute(nvivoRole.insert().values({
                            'Item1_Id': bindparam('AttributeId'),
                            'Item2_Id': bindparam('CategoryId'),
                            'TypeId':   literal_column('13'),
                            'Tag':      bindparam('NewAttributeTag')
                        }), sourceattribute)
                    #print sourceattribute
                    if sourceattribute['Type'] in DataTypeName.values():
                        datatype = DataTypeName.keys()[DataTypeName.values().index(sourceattribute['Type'])]
                    else:
                        datatype = 0;
                    nvivocon.execute(nvivoExtendedItem.insert().values({
                            'Item_Id': bindparam('AttributeId'),
                            'Properties': literal_column('\'<Properties xmlns="http://qsr.com.au/XMLSchema.xsd"><Property Key="DataType" Value="' + str(datatype) + '" /><Property Key="Length" Value="0" /><Property Key="EndNoteFieldTypeId" Value="-1" /></Properties>\'')
                    }), sourceattribute)
                    # Create unassigned and not applicable attribute values
                    sourceattribute['ValueId'] = uuid.uuid4()
                    # Save the attribute and 'Unassigned' value so that it can be filled in for all
                    # sources of the present category.
                    addedattributes.append({ 'CategoryId':     sourceattribute['CategoryId'],
                                             'AttributeId':    sourceattribute['AttributeId'],
                                             'DefaultValueId': sourceattribute['ValueId'] })
                    sourceattribute['Unassigned'] = unassignedLabel
                    nvivocon.execute(nvivoItem.insert().values({
                            'Id':       bindparam('ValueId'),
                            'Name':     bindparam('Unassigned'),
                            'Description': literal_column('\'\''),
                            'TypeId':   literal_column('21'),
                            'System':   literal_column('1'),
                            'ReadOnly': literal_column('0'),
                            'InheritPermissions': literal_column('1'),
                            'ColorArgb': literal_column('0')
                        }), sourceattribute)
                    nvivocon.execute(nvivoRole.insert().values({
                            'Item1_Id': bindparam('AttributeId'),
                            'Item2_Id': bindparam('ValueId'),
                            'TypeId':   literal_column('6'),
                            'Tag':      literal_column('0')
                        }), sourceattribute )
                    nvivocon.execute(nvivoExtendedItem.insert().values({
                            'Item_Id': bindparam('ValueId'),
                            'Properties': literal_column('\'<Properties xmlns="http://qsr.com.au/XMLSchema.xsd"><Property Key="IsDefault" Value="True"/></Properties>\'')
                    }), sourceattribute)
                    sourceattribute['ValueId'] = uuid.uuid4()
                    sourceattribute['NotApplicable'] = notapplicableLabel
                    nvivocon.execute(nvivoItem.insert().values({
                            'Id':       bindparam('ValueId'),
                            'Name':     bindparam('NotApplicable'),
                            'Description': literal_column('\'\''),
                            'TypeId':   literal_column('21'),
                            'System':   literal_column('1'),
                            'ReadOnly': literal_column('0'),
                            'InheritPermissions': literal_column('1'),
                            'ColorArgb': literal_column('0')
                        }), sourceattribute)
                    nvivocon.execute(nvivoRole.insert().values({
                            'Item1_Id': bindparam('AttributeId'),
                            'Item2_Id': bindparam('ValueId'),
                            'TypeId':   literal_column('6'),
                            'Tag':      literal_column('1')
                        }), sourceattribute )
                    nvivocon.execute(nvivoExtendedItem.insert().values({
                            'Item_Id': bindparam('ValueId'),
                            'Properties': literal_column('\'<Properties xmlns="http://qsr.com.au/XMLSchema.xsd"><Property Key="IsDefault" Value="False"/></Properties>\'')
                    }), sourceattribute)
                    sourceattribute['MaxValueTag'] = 1

                if sourceattribute['NewValueId'] == None:
                    print("Creating value '" + sourceattribute['PlainTextValue'] + "' for attribute '" + sourceattribute['PlainTextName'] + "' for source '" + sourceattribute['PlainTextSourceName'] + "'")
                    sourceattribute['NewValueId']  = uuid.uuid4()
                    sourceattribute['NewValueTag'] = sourceattribute['MaxValueTag'] + 1
                    nvivocon.execute(nvivoItem.insert().values({
                            'Id':       bindparam('NewValueId'),
                            'Name':     bindparam('Value'),
                            'Description': literal_column('\'\''),
                            'TypeId':   literal_column('21'),
                            'System':   literal_column('0'),
                            'ReadOnly': literal_column('0'),
                            'InheritPermissions': literal_column('1')
                        }), sourceattribute )
                    nvivocon.execute(nvivoRole.insert().values({
                            'Item1_Id': bindparam('AttributeId'),
                            'Item2_Id': bindparam('NewValueId'),
                            'TypeId':   literal_column('6'),
                            'Tag':      bindparam('NewValueTag')
                        }), sourceattribute )
                    nvivocon.execute(nvivoExtendedItem.insert().values({
                            'Item_Id': bindparam('NewValueId'),
                            'Properties': literal_column('\'<Properties xmlns="http://qsr.com.au/XMLSchema.xsd"><Property Key="IsDefault" Value="False"/></Properties>\'')
                    }), sourceattribute)

                if sourceattribute['NewValueId'] != sourceattribute['ExistingValueId']:
                    if sourceattribute['ExistingValueId'] != None:
                        print("Removing existing value of attribute '" + sourceattribute['PlainTextName'] + "' for source '" + sourceattribute['PlainTextSourceName'] + "'")
                        nvivocon.execute(nvivoRole.delete().values({
                                'Item1_Id': bindparam('Source'),
                                'Item2_Id': bindparam('ExistingValueId'),
                                'TypeId':   literal_column('7')
                            }), sourceattribute )
                    #print("Assigning value '" + sourceattribute['PlainTextValue'] + "' for attribute '" + sourceattribute['PlainTextName'] + "' for source '" + sourceattribute['PlainTextSourceName'] + "'")
                    nvivocon.execute(nvivoRole.insert().values({
                            'Item1_Id': bindparam('Source'),
                            'Item2_Id': bindparam('NewValueId'),
                            'TypeId':   literal_column('7')
                        }), sourceattribute )

        # Fill in default ('Undefined') value for all sources lacking an attribute value
        sel = select([
                nvivoSourceCategoryRole.c.Item1_Id.label('SourceId'),
                func.count(nvivoExistingValueRole.c.Item1_Id).label('ValueCount')
            ]).where(and_(
                nvivoSourceCategoryRole.c.TypeId   == literal_column('14'),
                nvivoSourceCategoryRole.c.Item2_Id == bindparam('CategoryId')
            )).group_by(nvivoSourceCategoryRole.c.Item1_Id)\
            .select_from(nvivoSourceCategoryRole.outerjoin(
                nvivoExistingValueRole.join(
                    nvivoSourceValueRole, and_(
                        nvivoSourceValueRole.c.Item2_Id == nvivoExistingValueRole.c.Item2_Id,
                        nvivoSourceValueRole.c.TypeId == literal_column('7')
                    )), and_(
                        nvivoExistingValueRole.c.TypeId == literal_column('6'),
                        nvivoExistingValueRole.c.Item1_Id == bindparam('AttributeId'),
                        nvivoSourceValueRole.c.Item1_Id == nvivoSourceCategoryRole.c.Item1_Id
            )))

        categorysel = select([nvivoCategory.c.Layout]).where(
                              nvivoCategory.c.Item_Id == bindparam('CategoryId'))
        for addedattribute in addedattributes:
            # Patch up Layout column in Category table
            category = dict(nvivocon.execute(categorysel, addedattribute).fetchone())
            layoutdoc = parseString(category['Layout'])
            followingelement = layoutdoc.documentElement.getElementsByTagName('SortedColumn')[0]
            previouselement = followingelement.previousSibling
            if previouselement != None and previouselement.tagName == 'Column':
                nextid = int(previouselement.getAttribute('Id')) + 1
            else:
                nextid = 0
            newelement = layoutdoc.createElement('Column')
            newelement.setAttribute('Guid', str(addedattribute['AttributeId']))
            newelement.setAttribute('Id', str(nextid))
            newelement.setAttribute('OrderId', str(nextid))
            newelement.setAttribute('Hidden', 'false')
            newelement.setAttribute('Size', '-1')
            layoutdoc.documentElement.insertBefore(newelement, followingelement)
            category['Layout'] = layoutdoc.documentElement.toxml()
            nvivocon.execute(nvivoCategory.update(), category)

            # Set value of undefined attribute to 'Unassigned'
            attributes = [dict(row) for row in nvivocon.execute(sel, addedattribute)]
            for attribute in attributes:
                if attribute['ValueCount'] == 0:
                    attribute.update(addedattribute)
                    #print(attribute)
                    nvivocon.execute(nvivoRole.insert().values({
                            'Item1_Id': bindparam('SourceId'),
                            'Item2_Id': bindparam('DefaultValueId'),
                            'TypeId':   literal_column('7')
                        }), attribute )

# Taggings
    if args.taggings != 'skip':
        print("Denormalising taggings")

        normTagging = normmd.tables['Tagging']
        taggings = [dict(row) for row in normdb.execute(select([
                normTagging.c.Source,
                normTagging.c.Node,
                normTagging.c.Memo,
                normTagging.c.Fragment,
                normTagging.c.CreatedBy,
                normTagging.c.CreatedDate,
                normTagging.c.ModifiedBy,
                normTagging.c.ModifiedDate]).where(
                normTagging.c.Node != None))]
            
        for tagging in taggings:
            matchfragment = re.match("([0-9]+):([0-9]+)(?:,([0-9]+)(?::([0-9]+))?)?", tagging['Fragment'])
            if matchfragment == None:
                raise RuntimeError, "ERROR: Unrecognised tagging fragment: " + tagging['Fragment']

            tagging['StartX'] = int(matchfragment.group(1))
            tagging['LengthX'] = int(matchfragment.group(2)) - tagging['StartX'] + 1
            tagging['StartY'] = None
            tagging['LengthY'] = None
            startY = matchfragment.group(3)
            if startY != None:
                tagging['StartY'] = int(startY)
                endY = matchfragment.group(4)
                if endY != None:
                    tagging['LengthY'] = int(endY) - tagging['StartY'] + 1
                    tagging['OfX'] = tagging['StartX']

            tagging['Id'] = uuid.uuid4()  # Not clear what purpose this field serves
            
            if tagging['Memo'] != None:
                print("Warning - Tagging contains memo - memo will be lost.")

        if len(taggings) > 0:
            nvivocon.execute(nvivoNodeReference.insert().values({
                        'Node_Item_Id':     bindparam('Node'),
                        'Source_Item_Id':   bindparam('Source'),
                        'ReferenceTypeId':  literal_column('0')
                }), taggings)

# Annotations
    if args.annotations != 'skip':
        print("Denormalising annotations")

        normTagging = normmd.tables['Tagging']
        annotations = [dict(row) for row in normdb.execute(select([
                normTagging.c.Source,
                normTagging.c.Node,
                normTagging.c.Memo,
                normTagging.c.Fragment,
                normTagging.c.CreatedBy,
                normTagging.c.CreatedDate,
                normTagging.c.ModifiedBy,
                normTagging.c.ModifiedDate]).where(
                normTagging.c.Node == None))]
            
        for annotation in annotations:
            matchfragment = re.match("([0-9]+):([0-9]+)(?:,([0-9]+)(?::([0-9]+))?)?", annotation['Fragment'])
            if matchfragment == None:
                raise RuntimeError, "ERROR: Unrecognised annotation fragment: " + annotation['Fragment']
            
            annotation['StartX'] = int(matchfragment.group(1))
            annotation['LengthX'] = int(matchfragment.group(2)) - annotation['StartX'] + 1
            annotation['StartY'] = None
            annotation['LengthY'] = None
            startY = matchfragment.group(3)
            if startY != None:
                annotation['StartY'] = int(startY)
                endY = matchfragment.group(4)
                if endY != None:
                    annotation['LengthY'] = int(endY) - annotation['StartY'] + 1

            annotation['Id'] = uuid.uuid4()  # Not clear what purpose this field serves

        if len(annotations) > 0:
            nvivocon.execute(nvivoAnnotation.insert().values({
                        'Item_Id':          bindparam('Source'),
                        'Text':             bindparam('Memo'),
                        # JS: Need to figure out ReferenceTypeId column
                        'ReferenceTypeId':  literal_column('0')
                }), annotations)

# All done.
    
    nvivotr.commit()

except exc.SQLAlchemyError:
    if nvivotr != None:
        nvivotr.rollback()
    raise
