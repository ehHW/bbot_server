from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatfriendship',
            name='remark_high',
            field=models.CharField(blank=True, default='', max_length=80),
        ),
        migrations.AddField(
            model_name='chatfriendship',
            name='remark_low',
            field=models.CharField(blank=True, default='', max_length=80),
        ),
    ]