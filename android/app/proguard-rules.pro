-keepattributes Signature
-keep class com.sintu.studio.api.** { *; }
-keep class com.sintu.studio.model.** { *; }

# Gson/Retrofit data models and API interfaces are reflected at runtime.
-keepattributes Signature,RuntimeVisibleAnnotations,RuntimeVisibleParameterAnnotations,AnnotationDefault
-keep class com.sintu.studio.** { *; }
