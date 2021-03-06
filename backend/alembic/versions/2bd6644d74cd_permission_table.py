"""permission table

Revision ID: 2bd6644d74cd
Revises: 623e28955744
Create Date: 2016-12-19 23:43:53.368261

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2bd6644d74cd'
down_revision = '623e28955744'
branch_labels = None
depends_on = None

def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('permissions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('server_id', sa.Integer(), nullable=False),
    sa.Column('channel_id', sa.Integer(), nullable=True),
    sa.Column('permission', sa.String(), nullable=False),
    sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], ),
    sa.ForeignKeyConstraint(['server_id'], ['servers.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('permission_server', 'permissions', ['server_id'], unique=False)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('permission_server', table_name='permissions')
    op.drop_table('permissions')
    # ### end Alembic commands ###
