from winotify import Notification, audio

toast = Notification(app_id="Winotify Test",
                     title="🔔 通知测试",
                     msg="如果你能看到这条消息，说明winotify库本身工作正常。",
                     duration="short")

# 暂时去掉set_audio，排除音频设置干扰
# toast.set_audio(audio.Silent, loop=False)
toast.show()