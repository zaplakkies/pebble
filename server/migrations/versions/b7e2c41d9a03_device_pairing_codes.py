"""device pairing codes

Revision ID: b7e2c41d9a03
Revises: 918c8d561946
Create Date: 2026-09-28 19:20:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7e2c41d9a03'
down_revision = '918c8d561946'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('device', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pair_code_hash', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('pair_expires', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('pair_failures', sa.Integer(), nullable=False,
                                      server_default='0'))
        batch_op.create_unique_constraint('uq_device_pair_code_hash', ['pair_code_hash'])


def downgrade():
    with op.batch_alter_table('device', schema=None) as batch_op:
        batch_op.drop_constraint('uq_device_pair_code_hash', type_='unique')
        batch_op.drop_column('pair_failures')
        batch_op.drop_column('pair_expires')
        batch_op.drop_column('pair_code_hash')
