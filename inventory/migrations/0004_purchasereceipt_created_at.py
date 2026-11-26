from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0003_stockmovement_reverses")]

    operations = [
        migrations.AddField(
            model_name="purchasereceipt", name="created_at", field=models.DateTimeField(null=True),
        ),
        migrations.AlterField(
            model_name="purchasereceipt", name="created_at", field=models.DateTimeField(auto_now_add=True, null=True),
        ),
    ]
