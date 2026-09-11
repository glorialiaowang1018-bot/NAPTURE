# 午睡家长端 Android App

这是家长端的 Android WebView App 壳，加载当前后端的 `/parent` 页面。

## 使用

1. 在 Android Studio 打开本目录：`parent_android_app`
2. 修改 `app/src/main/res/values/strings.xml` 里的 `parent_app_url`
   - 模拟器本机后端：`http://10.0.2.2:5000/parent`
   - 真机局域网：`http://电脑局域网IP:5000/parent`
   - 正式发布：`https://你的域名/parent`
3. 点击 Run 或 Build APK。

注意：真机异地使用时，后端必须部署到公网或学校服务器；只装 App 不会自动带走 Flask 后端。
