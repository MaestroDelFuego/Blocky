#version 150

uniform mat4 p3d_ModelViewProjectionMatrix;

in vec4 p3d_Vertex;
in vec4 p3d_Color;
in vec2 p3d_MultiTexCoord0;

out vec4 vertex_color;
out vec2 texcoord;

void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    vertex_color = p3d_Color;
    texcoord = p3d_MultiTexCoord0;
}
