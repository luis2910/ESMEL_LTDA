from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("FM", "0012_documento_categoria_tags"),
    ]

    operations = [
        migrations.AddField(
            model_name="cotizacion",
            name="tb_token",
            field=models.CharField(blank=True, max_length=120, null=True),
        ),
        migrations.AddField(
            model_name="cotizacion",
            name="tb_buy_order",
            field=models.CharField(blank=True, max_length=80, null=True),
        ),
        migrations.AddField(
            model_name="cotizacion",
            name="tb_session_id",
            field=models.CharField(blank=True, max_length=80, null=True),
        ),
        migrations.AddField(
            model_name="cotizacion",
            name="tb_status",
            field=models.CharField(blank=True, max_length=30, null=True),
        ),
        migrations.AddField(
            model_name="cotizacion",
            name="tb_auth_code",
            field=models.CharField(blank=True, max_length=40, null=True),
        ),
        migrations.AddField(
            model_name="cotizacion",
            name="tb_response_code",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="cotizacion",
            name="tb_card_last4",
            field=models.CharField(blank=True, max_length=10, null=True),
        ),
        migrations.AddField(
            model_name="cotizacion",
            name="tb_redirect_url",
            field=models.TextField(blank=True, null=True),
        ),
    ]
