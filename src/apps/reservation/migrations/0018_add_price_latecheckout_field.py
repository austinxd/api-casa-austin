
# Generated manually to fix missing price_latecheckout column

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reservation', '0017_reservation_price_latecheckout'),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE reservation_reservation ADD COLUMN IF NOT EXISTS price_latecheckout DECIMAL(10,2) NULL DEFAULT 0;",
            reverse_sql="ALTER TABLE reservation_reservation DROP COLUMN IF EXISTS price_latecheckout;"
        ),
    ]
