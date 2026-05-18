from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reservation', '0025_historicalreservation'),
    ]

    operations = [
        migrations.AddField(
            model_name='rentalreceipt',
            name='ai_description',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='rentalreceipt',
            name='ai_bank_origin',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='rentalreceipt',
            name='ai_bank_destination',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='rentalreceipt',
            name='ai_destination_account',
            field=models.CharField(blank=True, max_length=120, null=True),
        ),
        migrations.AddField(
            model_name='rentalreceipt',
            name='ai_currency',
            field=models.CharField(blank=True, max_length=10, null=True),
        ),
        migrations.AddField(
            model_name='rentalreceipt',
            name='ai_amount',
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=12, null=True,
            ),
        ),
        migrations.AddField(
            model_name='rentalreceipt',
            name='ai_deposit_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='rentalreceipt',
            name='ai_processed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='rentalreceipt',
            name='ai_error',
            field=models.TextField(blank=True, null=True),
        ),
    ]
